import equinox as eqx
import jax.numpy as jnp

from .fft import convolve, deconvolve, _get_fast_shape


class Renderer(eqx.Module):
    channel_map: (None, list, slice) = None

    def __init__(self, model_frame, obs_frame):
        self.channel_map = self.get_channel_map(model_frame, obs_frame)

    def __call__(self, model):
        raise NotImplementedError

    def get_channel_map(self, model_frame, obs_frame):
        if obs_frame.channels == model_frame.channels:
            return None
        try:
            channel_map = [
                list(model_frame.channels).index(c) for c in list(obs_frame.channels)
            ]
        except ValueError:
            msg = "Cannot match channels between model and observation.\n"
            msg += f"Got {model_frame.channels} and {obs_frame.channels}."
            raise ValueError(msg)

        min_channel = min(channel_map)
        max_channel = max(channel_map)
        if max_channel + 1 - min_channel == len(channel_map):
            channel_map = slice(min_channel, max_channel + 1)
        return channel_map

    def map_channels(self, model):
        """Map to model channels onto the observation channels
        Parameters
        ----------
        model: array
            The hyperspectral model
        Returns
        -------
        obs_model: array
            `model` mapped onto the observation channels
        """
        if self.channel_map is None:
            return model
        if isinstance(self.channel_map, (slice, list)):
            return model[self.channel_map, :, :]
        # not yet used by any renderer: full matrix mapping between model and observation channels
        return jnp.dot(self.channel_map, model)


class NoRenderer(Renderer):
    def __init__(self):
        self.channel_map = None

    def __call__(self, model):
        return model


class ConvolutionRenderer(Renderer):
    def __init__(self, model_frame, obs_frame):
        super().__init__(model_frame, obs_frame)

        # create PSF model
        psf = model_frame.psf()
        if len(psf.shape) == 2:  # only one image for all bands
            psf_model = jnp.tile(psf, (obs_frame.bbox.shape[0], 1, 1))
        else:
            psf_model = psf
        # make sure fft uses a shape large enough to cover the convolved model
        fft_shape = _get_fast_shape(model_frame.bbox.shape, psf_model.shape, padding=3, axes=(-2, -1))
        # compute and store diff kernel in Fourier space
        diff_kernel_fft = deconvolve(obs_frame.psf(), psf_model, axes=(-2, -1), fft_shape=fft_shape, return_fft=True)
        object.__setattr__(self, "_diff_kernel_fft", diff_kernel_fft)

    def __call__(self, model):
        # TODO: including slices
        model_ = self.map_channels(model)
        return convolve(model_, self._diff_kernel_fft, axes=(-2, -1))
