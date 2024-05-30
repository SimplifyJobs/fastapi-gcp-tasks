def task_default_options(**kwargs):
    """Wrapper to set default options for a cloud task."""

    def wrapper(fn):
        fn._delay_options = kwargs
        return fn

    return wrapper
