from .run_npm_script_command import RunNpmScriptCommand
import sublime_plugin


class ReloadNpmScriptsCommand(sublime_plugin.WindowCommand):
    def run(self):
        for cmd in sublime_plugin.all_command_classes[1]:
            if isinstance(cmd, RunNpmScriptCommand):
                self.window.status_message("NpmRunner: Reloading...")
                cmd.reload()
