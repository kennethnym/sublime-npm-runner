import sublime_plugin


def can_use_terminus():
    """Checks if Terminus can be used to display output"""
    window_cmds = sublime_plugin.all_command_classes[1]
    for cmd in window_cmds:
        if cmd.__name__ == "TerminusOpenCommand":
            return True
    return False


def run_with_terminus(cmd, cwd, window, use_panel):
    args = {
        "cmd": cmd,
        "cwd": cwd,
    }

    if use_panel:
        args["panel_name"] = "npmrunner.output"

    window.run_command("terminus_open", args)
