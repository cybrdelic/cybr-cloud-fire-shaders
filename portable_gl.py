"""Native OpenGL context selection; does not change or emulate shader equations."""
import os
import platform
import sys
import re


def desktop_identifiers(source):
    """Namespace a user noise3 function colliding with desktop GLSL's vec3 builtin.

    This changes only the function identifier and its call sites, not its body.
    ES source files remain unchanged. Desktop drivers differ in enforcing this.
    """
    if re.search(r'\bfloat\s+noise3\s*\(', source):
        return re.sub(r'\bnoise3(?=\s*\()', 'cybr_scalar_noise3', source)
    return source


def create_context(require=330, backend=None, **kwargs):
    import moderngl
    selected = backend or os.environ.get('CYBR_GL_BACKEND', 'auto')
    if selected not in ('auto', 'default', 'egl'):
        raise ValueError('CYBR_GL_BACKEND must be auto, default or egl')
    choices = (['egl', 'default'] if platform.system() == 'Linux' else ['default']) if selected == 'auto' else [selected]
    failures = []
    for choice in choices:
        try:
            options = dict(kwargs, require=require)
            if choice != 'default':
                options['backend'] = choice
            context = moderngl.create_standalone_context(**options)
            print(f'OpenGL {context.version_code}: {context.info.get("GL_RENDERER")} (backend={choice}, OS={platform.system()})', file=sys.stderr)
            return context
        except Exception as error:
            failures.append(f'{choice}: {type(error).__name__}: {error}')
    raise RuntimeError(
        f'No OpenGL {require // 100}.{require % 100 // 10} context on {platform.system()}. '
        'Install a working graphics driver; Linux headless runs need EGL/Mesa or an X display. '
        'Windows uses WGL and macOS uses CGL (OpenGL up to 4.1). '
        'CYBR_GL_BACKEND=default or egl selects a backend explicitly. Attempts: ' + '; '.join(failures))
