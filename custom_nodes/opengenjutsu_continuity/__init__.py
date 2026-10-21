"""OpenGenjutsu's narrow H3 file-contract adapter; Apache-2.0."""
from .nodes import OpenGenjutsuH3PublishFamily, OpenGenjutsuH3RestageFamily

NODE_CLASS_MAPPINGS = {
    'OpenGenjutsuH3PublishFamily': OpenGenjutsuH3PublishFamily,
    'OpenGenjutsuH3RestageFamily': OpenGenjutsuH3RestageFamily,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    'OpenGenjutsuH3PublishFamily': 'OpenGenjutsu H3 Publish Family (CPU)',
    'OpenGenjutsuH3RestageFamily': 'OpenGenjutsu H3 Restage Family (CPU)',
}
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
