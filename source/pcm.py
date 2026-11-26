import base64
import binascii
from dataclasses import dataclass

from source.programs import ProgramSpec

PCM_SAMPLE_BYTES = 2


class PCMFormatError(ValueError):
    pass


@dataclass(frozen=True)
class PCM:
    data: bytes

    @property
    def frame_count(self) -> int:
        return len(self.data) // PCM_SAMPLE_BYTES


def decode_pcm(value: object, spec: ProgramSpec) -> PCM:
    if not isinstance(value, dict) or value.keys() != {'sample_rate', 'channels', 'encoding', 'data'}:
        raise PCMFormatError('expected a PCM object with four fields')
    sample_rate = value['sample_rate']
    channels = value['channels']
    if type(sample_rate) is not int or sample_rate != spec.sample_rate:
        raise PCMFormatError('unexpected PCM sample rate')
    if type(channels) is not int or channels != spec.channels:
        raise PCMFormatError('unexpected PCM channel count')
    if value['encoding'] != spec.encoding or not isinstance(value['data'], str):
        raise PCMFormatError('expected Base64 PCM16 little-endian data')
    try:
        data = base64.b64decode(value['data'], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PCMFormatError('invalid Base64 PCM data') from exc
    if not data or len(data) % PCM_SAMPLE_BYTES:
        raise PCMFormatError('expected nonempty, frame-aligned PCM')
    return PCM(data)
