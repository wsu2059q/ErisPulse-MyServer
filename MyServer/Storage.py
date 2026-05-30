import time
from typing import Optional, List, Dict


class MachineStorage:
    _STORAGE_PREFIX = "mjj:machine:"
    _MACHINE_LIST_KEY = "mjj:machines"
    _STATUS_PREFIX = "mjj:status:"

    def __init__(self, storage):
        self.storage = storage

    def save_machine(self, machine: dict) -> bool:
        name = machine.get("name")
        if not name:
            return False

        machine["updated_at"] = time.time()
        if "added_at" not in machine:
            machine["added_at"] = time.time()

        self.storage.set(f"{self._STORAGE_PREFIX}{name}", machine)

        machines = self._get_machine_names()
        if name not in machines:
            machines.append(name)
            self.storage.set(self._MACHINE_LIST_KEY, machines)

        return True

    def get_machine(self, name: str) -> Optional[dict]:
        return self.storage.get(f"{self._STORAGE_PREFIX}{name}")

    def get_all_machines(self) -> List[dict]:
        names = self._get_machine_names()
        machines = []
        for name in names:
            machine = self.get_machine(name)
            if machine:
                status = self.get_status(name)
                machine["status"] = status.get("online", False)
                machines.append(machine)
        return machines

    def delete_machine(self, name: str) -> bool:
        if not self.get_machine(name):
            return False

        self.storage.delete(f"{self._STORAGE_PREFIX}{name}")
        self.storage.delete(f"{self._STATUS_PREFIX}{name}")

        machines = self._get_machine_names()
        if name in machines:
            machines.remove(name)
            self.storage.set(self._MACHINE_LIST_KEY, machines)

        return True

    def update_machine(self, name: str, updates: dict) -> bool:
        machine = self.get_machine(name)
        if not machine:
            return False

        machine.update(updates)
        machine["updated_at"] = time.time()
        self.storage.set(f"{self._STORAGE_PREFIX}{name}", machine)
        return True

    def save_status(self, name: str, status: dict):
        status["checked_at"] = time.time()
        self.storage.set(f"{self._STATUS_PREFIX}{name}", status)

    def get_status(self, name: str) -> dict:
        return self.storage.get(f"{self._STATUS_PREFIX}{name}", {})

    def _get_machine_names(self) -> List[str]:
        return self.storage.get(self._MACHINE_LIST_KEY, [])

    def machine_exists(self, name: str) -> bool:
        return self.get_machine(name) is not None
