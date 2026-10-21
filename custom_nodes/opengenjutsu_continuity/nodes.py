"""Legacy ComfyUI node API, CPU-only and importable without ComfyUI."""
from .family import publish, restage


class _FamilyNode:
    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('clip', 'manifest_json')
    FUNCTION = 'execute'
    OUTPUT_NODE = True
    CATEGORY = 'OpenGenjutsu/Continuity'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {name: ('STRING', {'default': '', 'multiline': False})
                             for name in ('video', 'mctx', 'conditioning')}}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # External bytes can change without graph input changes. Never reuse a
        # cached validation/manifest or a cached restager side effect.
        return float('nan')


class OpenGenjutsuH3PublishFamily(_FamilyNode):
    DESCRIPTION = ('Validate three explicit output-root family paths and expose their actual files to API v2. '
                   'Returns an optional output-relative clip only for an adjacent native family. No tensor load.')

    def execute(self, video, mctx, conditioning):
        return publish(video, mctx, conditioning)


class OpenGenjutsuH3RestageFamily(_FamilyNode):
    DESCRIPTION = ('Validate three independent SDK-resolved input filenames, copy exact bytes into a fresh '
                   'native adjacent output family, and atomically publish without overwrite. CPU-only.')

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema['required']['family_name'] = ('STRING', {'default': 'family', 'multiline': False})
        return schema

    def execute(self, video, mctx, conditioning, family_name):
        return restage(video, mctx, conditioning, family_name)
