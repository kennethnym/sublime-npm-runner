import os
import time
import re
import subprocess
import shutil
import threading
import json
from concurrent.futures.thread import ThreadPoolExecutor

from .terminus_integration import can_use_terminus, run_with_terminus
from .special_files import GITIGNORE, NPM_LOCK_FILE, PNPM_LOCK_FILE, YARN_LOCK_FILE
from .npm_script import NpmScript

import sublime
import sublime_plugin
import sublime_lib

ANSI_COLOR_CODE_REGEX = (
    r"[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]"
)
FOLDER_CHANGE_POLL_INTERVAL_MS = 1000


class RunNpmScriptCommand(sublime_plugin.WindowCommand):
    def __init__(self, window: sublime.Window) -> None:
        super().__init__(window)

        self.__is_indexing = True

        # Maps absolute paths of currently-opened folders in the current window
        # to a list of NPM scripts found inside each folder.
        self.__all_npm_scripts = {}

        # Maps absolute paths of package.json files to the package manager that should be used for it.
        self.__package_manager = {}

        threading.Thread(target=self.__index_folders, args=(window.folders(),)).start()
        threading.Thread(target=self.__poll_for_folder_changes).start()

    def is_visible(self) -> bool:
        return not self.__is_indexing and len(self.__all_npm_scripts) > 0

    def input(self, _):
        all_scripts = []
        for scripts in self.__all_npm_scripts.values():
            for script in scripts:
                all_scripts.append(script)

        return NpmScriptInputHandler(all_scripts)

    def run(self, npm_script):
        package_json_path, script_name = npm_script
        threading.Thread(
            target=self.__run_script, args=(package_json_path, script_name)
        ).start()

    def __poll_for_folder_changes(self):
        """
        Every now and then, check if the list of opened folders in the current window has changed.
        If new folders are added, index them.
        """
        prev_opened_folders = set(self.window.folders())
        while True:
            time.sleep(FOLDER_CHANGE_POLL_INTERVAL_MS)

            if self.__is_indexing:
                continue

            current_opened_folders = set(self.window.folders())
            added_folders = current_opened_folders - prev_opened_folders
            removed_folders = prev_opened_folders - current_opened_folders

            for folder in removed_folders:
                del self.__all_npm_scripts[folder]

            if len(added_folders) > 0:
                self.__index_folders(added_folders)

            prev_opened_folders = current_opened_folders

    def __index_folders(self, folders):
        self.__is_indexing = True
        self.window.status_message("NpmRunner: Indexing...")

        with ThreadPoolExecutor(max_workers=4) as executor:
            for opened_folder in folders:
                executor.submit(self.__index_package_json_in_folder, opened_folder)

        self.__is_indexing = False
        self.window.status_message("")

    def __index_package_json_in_folder(self, folder_path):
        package_json_paths = []
        has_git_ignore = os.path.exists(os.path.join(folder_path, GITIGNORE))

        project_files = []
        if has_git_ignore:
            stdout = subprocess.check_output(
                ["git", "ls-files"],
                cwd=folder_path,
            )
            project_files = stdout.decode("utf-8").strip().split(os.linesep)
        else:
            project_files = os.listdir(folder_path)

        package_json_paths += [
            os.path.join(folder_path, path)
            for path in project_files
            if os.path.basename(path) == "package.json"
        ]
        package_manager = self.__detect_package_manager_for_folder(folder_path)

        with ThreadPoolExecutor(max_workers=4) as executor:
            for path in package_json_paths:
                self.__package_manager[path] = package_manager
                executor.submit(self.__find_scripts_in_package_json, path, folder_path)

    def __find_scripts_in_package_json(self, path, project_path):
        with open(path) as f:
            package_json = json.load(f)

            package_name = package_json["name"] if package_json["name"] else ""
            scripts = (
                [
                    NpmScript(
                        script_name=script_name,
                        package_name=package_name,
                        package_json_path=path,
                        project_path=project_path,
                    )
                    for script_name in package_json["scripts"]
                ]
                if package_json["scripts"]
                else []
            )

            if len(scripts) <= 0:
                return

            if project_path in self.__all_npm_scripts:
                self.__all_npm_scripts[project_path] += scripts
            else:
                self.__all_npm_scripts[project_path] = scripts

    def __detect_package_manager_for_folder(self, folder_path):
        if os.path.exists(os.path.join(folder_path, NPM_LOCK_FILE)):
            return "npm"

        if os.path.exists(os.path.join(folder_path, YARN_LOCK_FILE)):
            return "yarn"

        if os.path.exists(os.path.join(folder_path, PNPM_LOCK_FILE)):
            return "pnpm"

        return ""

    def __run_script(self, package_json_path, script_name):
        package_manager = self.__package_manager[package_json_path]
        if not package_manager:
            sublime.error_message("No package manager found.")
            return

        self.window.create_output_panel("npmrunner.output")
        output_panel = sublime_lib.OutputPanel(self.window, name="npmrunner.output")
        package_manager_path = shutil.which(package_manager)

        if can_use_terminus():
            run_with_terminus(
                cmd=[package_manager_path, "run", script_name],
                cwd=os.path.dirname(package_json_path),
                window=self.window,
                use_panel=True,
            )
        else:
            p = subprocess.Popen(
                [package_manager_path, "run", script_name],
                cwd=os.path.dirname(package_json_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            if p.stdout:
                output_panel.show()

                for line in iter(p.stdout.readline, b""):
                    output_panel.write(
                        re.sub(
                            ANSI_COLOR_CODE_REGEX,
                            "",
                            line.decode(),
                        )
                    )


class NpmScriptInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, scripts) -> None:
        super().__init__()
        self.__scripts = scripts

    def list_items(self):
        return [
            sublime.ListInputItem(
                text="{}: {}".format(script.package_name, script.script_name)
                if script.package_name
                else script.script_name,
                details=os.path.relpath(script.package_json_path, script.project_path),
                value=[script.package_json_path, script.script_name],
                kind=sublime.KIND_AMBIGUOUS,
            )
            for script in self.__scripts
        ]
