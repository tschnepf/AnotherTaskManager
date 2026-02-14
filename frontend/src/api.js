const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

async function request(path, { method = 'GET', token, body } = {}) {
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  const headers = {}
  if (!isFormData) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? (isFormData ? body : JSON.stringify(body)) : undefined,
  })

  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await response.json() : null

  if (!response.ok) {
    const message = data?.message || data?.detail || `Request failed (${response.status})`
    throw new Error(message)
  }

  return data
}

export async function login(email, password) {
  return request('/auth/login', { method: 'POST', body: { email, password } })
}

export async function getTasks(token, params = {}) {
  const query = new URLSearchParams({
    page: '1',
    page_size: '50',
    sort: 'position',
    order: 'asc',
  })
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    query.set(key, String(value))
  })
  return request(`/tasks/?${query.toString()}`, { token })
}

export async function getProjects(token, params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    query.set(key, String(value))
  })
  const suffix = query.toString()
  const path = suffix ? `/projects/?${suffix}` : '/projects/'
  return request(path, { token })
}

export async function createProject(token, name, area = 'work') {
  return request('/projects/', {
    method: 'POST',
    token,
    body: { name, area },
  })
}

export async function quickAddTask(token, title, area = 'work', projectId = '', priority = null) {
  const body = { title, area, status: 'inbox' }
  if (projectId) {
    body.project = projectId
  }
  if (priority !== null) {
    body.priority = priority
  }
  return request('/tasks/', {
    method: 'POST',
    token,
    body,
  })
}

export async function updateTask(token, taskId, payload) {
  return request(`/tasks/${taskId}/`, {
    method: 'PATCH',
    token,
    body: payload,
  })
}

export async function setTaskCompleted(token, taskId, completed) {
  const action = completed ? 'complete' : 'reopen'
  return request(`/tasks/${taskId}/${action}/`, {
    method: 'POST',
    token,
  })
}

export async function deleteTask(token, taskId) {
  return request(`/tasks/${taskId}/`, {
    method: 'DELETE',
    token,
  })
}

export async function reorderTask(token, taskId, targetTaskId, placement) {
  return request(`/tasks/${taskId}/reorder/`, {
    method: 'POST',
    token,
    body: { target_task_id: targetTaskId, placement },
  })
}

export async function uploadTaskAttachment(token, taskId, file) {
  const body = new FormData()
  body.append('file', file)
  return request(`/tasks/${taskId}/attachments/upload/`, {
    method: 'POST',
    token,
    body,
  })
}

export async function downloadDatabaseBackup(token) {
  const headers = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE}/ops/database/backup`, {
    method: 'GET',
    headers,
  })

  if (!response.ok) {
    const contentType = response.headers.get('content-type') || ''
    const data = contentType.includes('application/json') ? await response.json() : null
    const message = data?.message || data?.detail || `Request failed (${response.status})`
    throw new Error(message)
  }

  const blob = await response.blob()
  const contentDisposition = response.headers.get('content-disposition') || ''
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/)
  const filename = filenameMatch?.[1] || 'taskhub-backup.json'
  return { blob, filename }
}

export async function restoreDatabaseBackup(token, backupFile, confirm = 'RESTORE') {
  const body = new FormData()
  body.append('backup_file', backupFile)
  body.append('confirm', confirm)
  return request('/ops/database/restore', {
    method: 'POST',
    token,
    body,
  })
}
