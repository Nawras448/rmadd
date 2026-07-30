class RmaddGuiApp:
    def __init__(self, container):
        self._container = container
        self.system_service = container.get_system_service()
        self.package_service = container.get_package_service()
        self.hardware_service = container.get_hardware_service()

    def run(self):
        print("GUI mode not yet implemented. Use 'tui' or 'cli' mode.")
