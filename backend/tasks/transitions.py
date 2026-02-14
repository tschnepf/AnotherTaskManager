from tasks.models import Task

ALLOWED_TRANSITIONS = {
    Task.Status.INBOX: {Task.Status.NEXT, Task.Status.WAITING, Task.Status.SOMEDAY, Task.Status.DONE, Task.Status.ARCHIVED},
    Task.Status.NEXT: {Task.Status.WAITING, Task.Status.SOMEDAY, Task.Status.DONE, Task.Status.ARCHIVED},
    Task.Status.WAITING: {Task.Status.NEXT, Task.Status.SOMEDAY, Task.Status.DONE, Task.Status.ARCHIVED},
    Task.Status.SOMEDAY: {Task.Status.NEXT, Task.Status.WAITING, Task.Status.DONE, Task.Status.ARCHIVED},
    Task.Status.DONE: {Task.Status.NEXT, Task.Status.WAITING, Task.Status.SOMEDAY, Task.Status.ARCHIVED},
    Task.Status.ARCHIVED: {Task.Status.INBOX, Task.Status.NEXT, Task.Status.WAITING, Task.Status.SOMEDAY},
}


def is_valid_transition(old_status: str, new_status: str) -> bool:
    if old_status == new_status:
        return True
    return new_status in ALLOWED_TRANSITIONS.get(old_status, set())
