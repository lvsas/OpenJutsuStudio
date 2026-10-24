"""Read-only interpretation of installed ComfyUI dynamic input schemas."""


def autogrow_member_spec(spec, member):
    """Return the declared member's input spec; reject unsupported/unknown fields.

    V3 autogrow uses either explicit names (e.g. math variables) or a numbered
    prefix/max (e.g. reference images). A named declaration need not have a max.
    No graph or target schema is rewritten and no capacity is invented.
    """
    invalid = 'The graph input is not supported by the installed dynamic node schema.'
    if not isinstance(spec, (list, tuple)) or len(spec) != 2 or spec[0] != 'COMFY_AUTOGROW_V3':
        raise ValueError(invalid)
    options = spec[1]
    config = options.get('template') if isinstance(options, dict) else None
    if not isinstance(config, dict) or not isinstance(member, str):
        raise ValueError(invalid)
    if 'names' in config and 'prefix' not in config:
        names = config['names']
        if (not isinstance(names, list) or not names
                or any(not isinstance(name, str) or not name for name in names)
                or len(set(names)) != len(names) or member not in names):
            raise ValueError(invalid)
    elif 'prefix' in config and 'names' not in config:
        prefix, maximum = config['prefix'], config.get('max')
        if not isinstance(prefix, str) or not prefix or type(maximum) is not int or maximum < 0:
            raise ValueError(invalid)
        suffix = member.removeprefix(prefix)
        if (not member.startswith(prefix) or not suffix.isascii() or not suffix.isdecimal()
                or str(int(suffix)) != suffix or int(suffix) >= maximum):
            raise ValueError(invalid)
    else:
        raise ValueError(invalid)
    inputs = config.get('input', {})
    required = inputs.get('required', {}) if isinstance(inputs, dict) else {}
    if not isinstance(required, dict) or len(required) != 1:
        raise ValueError(invalid)
    value = next(iter(required.values()))
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(invalid)
    return value
