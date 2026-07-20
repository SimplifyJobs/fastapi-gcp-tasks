"""Callback URL option resolution shared by route builders."""


def resolve_callback_base_url(
    *,
    callback_base_url: str | None,
    base_url: str | None,
    default: str | None = None,
) -> str:
    """Resolve the preferred callback URL option and its legacy alias."""
    if callback_base_url is not None and base_url is not None:
        raise TypeError("Pass callback_base_url or base_url, not both")
    if callback_base_url is not None:
        return callback_base_url
    if base_url is not None:
        return base_url
    if default is not None:
        return default
    raise TypeError("Missing required keyword argument: callback_base_url (or legacy base_url)")
