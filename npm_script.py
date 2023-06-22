class NpmScript:
    def __init__(self, package_json_path, project_path, package_name, script_name):
        self.package_json_path = package_json_path
        self.package_name = package_name
        self.script_name = script_name
        self.project_path = project_path
