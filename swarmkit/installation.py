"""Install a small launcher without modifying shell configuration or mission state."""

import os
from pathlib import Path
import shlex
import sys
import tempfile

from .core import CLI_PATH, SwarmError


def install_launcher(bin_dir):
    directory = Path(bin_dir).expanduser().absolute()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "swarmctl"
    content = (
        "#!/bin/sh\n"
        "# Swarmkit launcher: keep the referenced package directory in place.\n"
        'exec %s %s "$@"\n' % (shlex.quote(sys.executable), shlex.quote(str(CLI_PATH)))
    ).encode("utf-8")
    # Publish only a complete executable. A concurrent installer or an existing
    # command wins; never replace a file or follow a destination symlink.
    with tempfile.NamedTemporaryFile(prefix=".swarmctl-", dir=directory) as temporary:
        temporary.write(content)
        temporary.flush()
        os.chmod(temporary.name, 0o755)
        try:
            os.link(temporary.name, destination)
        except FileExistsError:
            if (
                destination.is_symlink()
                or not destination.is_file()
                or destination.stat().st_size != len(content)
                or destination.read_bytes() != content
                or not os.access(destination, os.X_OK)
            ):
                raise SwarmError(
                    "Refusing to replace %s. Choose another --bin-dir, or inspect and remove "
                    "the existing launcher before reinstalling." % destination
                ) from None
    return destination
