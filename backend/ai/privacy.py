
def cloud_allowed(org_allow_cloud_ai: bool, task_allow_cloud_processing: bool | None) -> bool:
    if task_allow_cloud_processing is None:
        return bool(org_allow_cloud_ai)
    return bool(task_allow_cloud_processing)
