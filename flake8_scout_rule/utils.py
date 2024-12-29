import os


def normalize_filename(filename: str) -> str:
    """
    Returns the normalized filename.

    :return: The normalized filename.
    :rtype: str
    """
    # If the filename starts with "./", its already relative
    if filename.startswith("./"):
        return filename.removeprefix("./")

    # os.path.relpath() doesn't work as expected in some cases, so we have to do this manually
    cwd = os.getcwd() + "/"
    realcwd = os.path.realpath(cwd)
    if filename.startswith(cwd):
        return filename.removeprefix(cwd)
    if filename.startswith(realcwd):
        return filename.removeprefix(realcwd)

    filename_real = os.path.realpath(filename)
    if filename_real.startswith(cwd):
        return filename_real.removeprefix(cwd)
    if filename_real.startswith(realcwd):
        return filename_real.removeprefix(realcwd)

    return filename.removeprefix(".").removeprefix("/")
