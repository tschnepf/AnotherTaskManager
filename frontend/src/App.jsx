import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { PDFWorker, getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'

import {
  createProject,
  deleteTask,
  getProjects,
  getTasks,
  login,
  quickAddTask,
  reorderTask,
  setTaskCompleted,
  uploadTaskAttachment,
  updateTask,
} from './api'
import './App.css'

const TOKEN_KEY = 'taskhub_access_token'
const DAY_IN_MS = 24 * 60 * 60 * 1000
const PRIORITY_OPTIONS = [
  { value: '', label: '-' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]
const PREVIEWABLE_IMAGE_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'bmp',
  'svg',
  'avif',
])

function priorityValueFromLevel(level) {
  if (level === 'high') return 5
  if (level === 'medium') return 3
  if (level === 'low') return 1
  return null
}

function priorityLevelFromValue(priority) {
  if (priority === null || priority === undefined) {
    return ''
  }
  if (priority >= 4) return 'high'
  if (priority >= 2) return 'medium'
  return 'low'
}

function priorityClassFromLevel(level) {
  if (level === 'high') return 'priority-text-high'
  if (level === 'medium') return 'priority-text-medium'
  if (level === 'low') return 'priority-text-low'
  return ''
}

function normalizeAttachments(attachments) {
  if (!Array.isArray(attachments)) {
    return []
  }
  return attachments
    .map((attachment) => {
      if (!attachment || typeof attachment !== 'object') {
        return null
      }
      const name = String(attachment.name || '').trim()
      const rawUrl = String(attachment.url || '').trim()
      let url = rawUrl
      if (rawUrl) {
        try {
          const parsed = new URL(rawUrl, window.location.origin)
          if (parsed.pathname.startsWith('/media/')) {
            url = `${window.location.origin}${parsed.pathname}${parsed.search}${parsed.hash}`
          }
        } catch {
          url = rawUrl
        }
      }
      if (!url) {
        return null
      }
      return { name: name || 'Attachment', url }
    })
    .filter(Boolean)
}

function attachmentExtension(attachment) {
  const name = String(attachment?.name || '').trim()
  const url = String(attachment?.url || '').trim()
  const candidate = name || url
  if (!candidate) {
    return ''
  }

  let pathname = candidate
  try {
    pathname = new URL(candidate, window.location.origin).pathname
  } catch {
    pathname = candidate
  }

  const filename = pathname.split('/').pop() || pathname
  const dotIndex = filename.lastIndexOf('.')
  if (dotIndex <= 0 || dotIndex >= filename.length - 1) {
    return ''
  }
  return filename.slice(dotIndex + 1).toLowerCase()
}

function attachmentPreviewType(attachment) {
  const extension = attachmentExtension(attachment)
  if (!extension) {
    return ''
  }
  if (extension === 'pdf') {
    return 'pdf'
  }
  if (PREVIEWABLE_IMAGE_EXTENSIONS.has(extension)) {
    return 'image'
  }
  return ''
}

function isModifiedLinkClick(event) {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.altKey ||
    event.shiftKey
  )
}

function EyeIcon() {
  return (
    <svg
      className="attachment-action-icon"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M2 12C3.8 8.6 7.4 6.5 12 6.5C16.6 6.5 20.2 8.6 22 12C20.2 15.4 16.6 17.5 12 17.5C7.4 17.5 3.8 15.4 2 12Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.8" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg
      className="attachment-action-icon"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M12 3.5V14.5M12 14.5L8.2 10.7M12 14.5L15.8 10.7"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M5 17.5H19V20.5H5V17.5Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function PdfCanvasViewer({ url, fileName }) {
  const containerRef = useRef(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    let loadingTask = null
    let pdfWorker = null
    const activeRenderTasks = []

    async function renderPdf() {
      setIsLoading(true)
      setError('')

      const container = containerRef.current
      if (!container) {
        setIsLoading(false)
        return
      }
      container.replaceChildren()

      try {
        const response = await fetch(url, { credentials: 'include' })
        if (!response.ok) {
          throw new Error(`Failed to load PDF (${response.status})`)
        }
        const pdfBytes = await response.arrayBuffer()

        // Prefer an explicit bundled worker so rendering doesn't depend on browser PDF behavior.
        try {
          const workerPort = new Worker(
            new URL('pdfjs-dist/legacy/build/pdf.worker.mjs', import.meta.url),
            { type: 'module' }
          )
          pdfWorker = new PDFWorker({ port: workerPort })
        } catch {
          pdfWorker = null
        }

        loadingTask = getDocument({
          data: pdfBytes,
          ...(pdfWorker ? { worker: pdfWorker } : {}),
        })
        const pdfDocument = await loadingTask.promise
        if (cancelled) {
          return
        }

        for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
          const page = await pdfDocument.getPage(pageNumber)
          if (cancelled) {
            return
          }

          const viewport = page.getViewport({ scale: 1.4 })
          const pageWrapper = document.createElement('div')
          pageWrapper.className = 'pdf-canvas-page'

          const canvas = document.createElement('canvas')
          canvas.className = 'pdf-canvas'
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)

          const canvasContext = canvas.getContext('2d')
          if (!canvasContext) {
            throw new Error('Could not initialize PDF canvas')
          }

          pageWrapper.appendChild(canvas)
          container.appendChild(pageWrapper)

          const renderTask = page.render({ canvasContext, viewport })
          activeRenderTasks.push(renderTask)
          await renderTask.promise
        }

        if (!cancelled) {
          setIsLoading(false)
        }
      } catch (cause) {
        if (!cancelled) {
          const message = cause instanceof Error ? cause.message : 'Unable to preview this PDF.'
          setError(message)
          console.error('Task Hub PDF preview failed:', cause)
          setIsLoading(false)
        }
      }
    }

    renderPdf()

    return () => {
      cancelled = true
      activeRenderTasks.forEach((task) => {
        if (typeof task.cancel === 'function') {
          try {
            task.cancel()
          } catch {
            // Ignore cancellation errors while unmounting.
          }
        }
      })
      if (loadingTask) {
        loadingTask.destroy()
      }
      if (pdfWorker) {
        pdfWorker.destroy()
      }
    }
  }, [url])

  if (error) {
    return (
      <div className="pdf-viewer-error">
        <p>Unable to preview this PDF in-app.</p>
        <p className="pdf-viewer-error-detail">{error}</p>
        <a href={url} target="_blank" rel="noreferrer">
          Open in browser
        </a>
      </div>
    )
  }

  return (
    <div className="pdf-viewer-shell">
      {isLoading ? <p className="pdf-viewer-status">Loading PDF...</p> : null}
      <div
        ref={containerRef}
        className={isLoading ? 'pdf-canvas-list pdf-canvas-list-hidden' : 'pdf-canvas-list'}
        aria-label={`PDF preview for ${fileName}`}
      />
    </div>
  )
}

function formatCreatedTimestamp(value) {
  if (!value) {
    return '—'
  }
  const createdAt = new Date(value)
  if (Number.isNaN(createdAt.getTime())) {
    return '—'
  }

  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const createdDayStart = new Date(
    createdAt.getFullYear(),
    createdAt.getMonth(),
    createdAt.getDate()
  )
  const dayDiff = Math.floor((todayStart.getTime() - createdDayStart.getTime()) / DAY_IN_MS)

  if (dayDiff <= 0) {
    return 'Today'
  }
  if (dayDiff === 1) {
    return 'Yesterday'
  }
  if (dayDiff <= 7) {
    return `${dayDiff} days ago`
  }
  if (dayDiff <= 30) {
    const weeks = Math.min(4, Math.floor(dayDiff / 7))
    return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`
  }

  const months = Math.floor(dayDiff / 30)
  return months === 1 ? '1 month ago' : `${months} months ago`
}

function AuthPage({ onLoggedIn }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    try {
      const data = await login(email, password)
      onLoggedIn(data.access)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1>Task Hub</h1>
        <p>Sign in</p>
        <label htmlFor="email">Email</label>
        <input id="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error ? <p className="error-text">{error}</p> : null}
        <button type="submit">Log In</button>
      </form>
    </div>
  )
}

function QuickAdd({ token, projects, onTaskCreated, onProjectCreated, inline = false }) {
  const [title, setTitle] = useState('')
  const [area, setArea] = useState('work')
  const [priorityLevel, setPriorityLevel] = useState('')
  const [projectQuery, setProjectQuery] = useState('')
  const [projectId, setProjectId] = useState('')
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  const [projectSuggestions, setProjectSuggestions] = useState([])
  const [loadingProjectSuggestions, setLoadingProjectSuggestions] = useState(false)
  const [highlightedProjectIndex, setHighlightedProjectIndex] = useState(-1)
  const [creatingProject, setCreatingProject] = useState(false)
  const [error, setError] = useState('')
  const projectPickerRef = useRef(null)
  const areaProjects = useMemo(
    () => projects.filter((project) => project.area === area),
    [projects, area]
  )
  const normalizedQuery = projectQuery.trim().toLowerCase()
  const filteredProjects = useMemo(() => projectSuggestions.slice(0, 8), [projectSuggestions])
  const exactMatch = useMemo(
    () => projectSuggestions.find((project) => project.name.toLowerCase() === normalizedQuery),
    [projectSuggestions, normalizedQuery]
  )

  useEffect(() => {
    if (projectId && !areaProjects.some((project) => project.id === projectId)) {
      setProjectId('')
      setProjectQuery('')
    }
  }, [areaProjects, projectId])

  useEffect(() => {
    if (!projectMenuOpen || !filteredProjects.length) {
      setHighlightedProjectIndex(-1)
      return
    }
    if (highlightedProjectIndex >= filteredProjects.length) {
      setHighlightedProjectIndex(0)
    }
  }, [filteredProjects, projectMenuOpen, highlightedProjectIndex])

  useEffect(() => {
    if (!projectMenuOpen || !normalizedQuery) {
      setProjectSuggestions([])
      setLoadingProjectSuggestions(false)
      return
    }

    let active = true
    setLoadingProjectSuggestions(true)
    getProjects(token, { area, q: normalizedQuery, limit: 50 })
      .then((projectData) => {
        if (!active) {
          return
        }
        setProjectSuggestions(Array.isArray(projectData) ? projectData : [])
      })
      .catch(() => {
        if (!active) {
          return
        }
        setProjectSuggestions([])
      })
      .finally(() => {
        if (!active) {
          return
        }
        setLoadingProjectSuggestions(false)
      })

    return () => {
      active = false
    }
  }, [token, area, normalizedQuery, projectMenuOpen])

  useEffect(() => {
    function handleOutsideClick(event) {
      if (projectPickerRef.current && !projectPickerRef.current.contains(event.target)) {
        setProjectMenuOpen(false)
        setHighlightedProjectIndex(-1)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [])

  function selectProject(project) {
    setProjectId(project.id)
    setProjectQuery(project.name)
    setProjectMenuOpen(false)
    setHighlightedProjectIndex(-1)
    setError('')
  }

  async function createProjectFromQuery() {
    const name = projectQuery.trim()
    if (!name) {
      return
    }
    setCreatingProject(true)
    setError('')
    try {
      const created = await createProject(token, name, area)
      onProjectCreated(created)
      selectProject(created)
    } catch (e) {
      setError(e.message)
    } finally {
      setCreatingProject(false)
    }
  }

  function handleProjectInputChange(value) {
    setProjectQuery(value)
    setProjectMenuOpen(Boolean(value.trim()))
    setHighlightedProjectIndex(-1)
    const selected = areaProjects.find((project) => project.id === projectId)
    if (selected && selected.name !== value) {
      setProjectId('')
    }
  }

  function handleProjectInputKeyDown(event) {
    if (!projectMenuOpen || !filteredProjects.length) {
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlightedProjectIndex((current) => (current + 1) % filteredProjects.length)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlightedProjectIndex((current) =>
        current <= 0 ? filteredProjects.length - 1 : current - 1
      )
      return
    }
    if (event.key === 'Enter' && highlightedProjectIndex >= 0) {
      event.preventDefault()
      selectProject(filteredProjects[highlightedProjectIndex])
    }
  }

  async function submit(event) {
    event.preventDefault()
    if (!title.trim()) {
      return
    }
    let resolvedProjectId = projectId
    if (!resolvedProjectId && projectQuery.trim()) {
      if (exactMatch) {
        resolvedProjectId = exactMatch.id
        setProjectId(exactMatch.id)
        setProjectQuery(exactMatch.name)
      } else {
        setError('Select a matching project or create one from the suggestions.')
        return
      }
    }

    setError('')
    try {
      await quickAddTask(
        token,
        title.trim(),
        area,
        resolvedProjectId,
        priorityValueFromLevel(priorityLevel)
      )
      setTitle('')
      setPriorityLevel('')
      onTaskCreated()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <form className={inline ? 'quick-add quick-add-inline' : 'quick-add'} onSubmit={submit}>
      <input
        placeholder="Quick add task"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="Quick add task"
      />
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Area">
        <option value="work">Work</option>
        <option value="personal">Personal</option>
      </select>
      <select
        className={`quick-add-priority-select ${priorityClassFromLevel(priorityLevel)}`.trim()}
        value={priorityLevel}
        onChange={(e) => setPriorityLevel(e.target.value)}
        aria-label="Priority"
      >
        {PRIORITY_OPTIONS.map((option) => (
          <option key={option.value || 'none'} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <div className="project-picker" ref={projectPickerRef}>
        <input
          value={projectQuery}
          onChange={(e) => handleProjectInputChange(e.target.value)}
          onFocus={() => setProjectMenuOpen(Boolean(projectQuery.trim()))}
          onKeyDown={handleProjectInputKeyDown}
          placeholder="Project (type to search or create)"
          aria-label="Project"
        />
        {projectMenuOpen && normalizedQuery ? (
          <div className="project-suggestions" role="listbox">
            {filteredProjects.map((project, index) => (
              <button
                key={project.id}
                type="button"
                className={
                  highlightedProjectIndex === index
                    ? 'project-suggestion project-suggestion-highlighted'
                    : 'project-suggestion'
                }
                onClick={() => selectProject(project)}
                onMouseEnter={() => setHighlightedProjectIndex(index)}
                aria-selected={highlightedProjectIndex === index}
              >
                {project.name}
              </button>
            ))}
            {!exactMatch && projectQuery.trim() ? (
              <button
                type="button"
                className="project-suggestion project-suggestion-create"
                onClick={createProjectFromQuery}
                disabled={creatingProject}
              >
                {creatingProject ? 'Creating...' : `Create "${projectQuery.trim()}"`}
              </button>
            ) : null}
            {!filteredProjects.length && loadingProjectSuggestions ? (
              <div className="project-suggestion project-suggestion-empty">Searching...</div>
            ) : null}
          </div>
        ) : null}
      </div>
      <button type="submit">Add</button>
      {error ? <span className="error-text">{error}</span> : null}
    </form>
  )
}

function Dashboard({ token, onLogout }) {
  const [tasks, setTasks] = useState([])
  const [taskTotal, setTaskTotal] = useState(0)
  const [projects, setProjects] = useState([])
  const [activeView, setActiveView] = useState({ type: 'all' })
  const [groupByPriority, setGroupByPriority] = useState(false)
  const [error, setError] = useState('')
  const [reloadCounter, setReloadCounter] = useState(0)
  const [updatingTaskIds, setUpdatingTaskIds] = useState(new Set())
  const [deletingTaskIds, setDeletingTaskIds] = useState(new Set())
  const [openDeleteTaskId, setOpenDeleteTaskId] = useState('')
  const [draggedTaskId, setDraggedTaskId] = useState('')
  const [dropTarget, setDropTarget] = useState(null)
  const [expandedTaskId, setExpandedTaskId] = useState('')
  const [detailsNotes, setDetailsNotes] = useState('')
  const [detailsAttachments, setDetailsAttachments] = useState([])
  const [isAttachmentDragOver, setIsAttachmentDragOver] = useState(false)
  const [attachmentPreview, setAttachmentPreview] = useState(null)
  const projectNameById = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects]
  )

  const workProjects = useMemo(
    () => projects.filter((project) => project.area === 'work'),
    [projects]
  )
  const personalProjects = useMemo(
    () => projects.filter((project) => project.area === 'personal'),
    [projects]
  )
  const filteredTasks = useMemo(() => tasks, [tasks])
  const activeViewLabel = useMemo(() => {
    if (activeView.type === 'all') {
      return 'All Tasks'
    }
    if (activeView.type === 'area') {
      return activeView.area === 'work' ? 'Work' : 'Personal'
    }
    if (activeView.type === 'project') {
      return projectNameById[activeView.projectId] || 'Project'
    }
    return 'All Tasks'
  }, [activeView, projectNameById])
  const taskCountLabel = useMemo(() => `${taskTotal} tasks`, [taskTotal])
  const taskQueryParams = useMemo(() => {
    const params = {}
    if (activeView.type === 'area') {
      params.area = activeView.area
    }
    if (activeView.type === 'project') {
      params.project_id = activeView.projectId
    }
    if (groupByPriority) {
      params.sort_mode = 'priority_manual'
    }
    return params
  }, [activeView, groupByPriority])

  useEffect(() => {
    if (activeView.type !== 'project') {
      return
    }
    if (!projects.some((project) => project.id === activeView.projectId)) {
      setActiveView({ type: 'all' })
    }
  }, [activeView, projects])

  useEffect(() => {
    if (!openDeleteTaskId) {
      return undefined
    }

    function handleOutsideClick(event) {
      const actionCell = event.target.closest(`[data-task-action-id="${openDeleteTaskId}"]`)
      if (!actionCell) {
        setOpenDeleteTaskId('')
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [openDeleteTaskId])

  useEffect(() => {
    if (!expandedTaskId) {
      return
    }
    if (!tasks.some((task) => task.id === expandedTaskId)) {
      setExpandedTaskId('')
      setDetailsNotes('')
      setDetailsAttachments([])
      setIsAttachmentDragOver(false)
      setAttachmentPreview(null)
    }
  }, [expandedTaskId, tasks])

  useEffect(() => {
    if (!attachmentPreview) {
      return undefined
    }

    function handleEscape(event) {
      if (event.key === 'Escape') {
        setAttachmentPreview(null)
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('keydown', handleEscape)
    }
  }, [attachmentPreview])

  useEffect(() => {
    let active = true
    getProjects(token)
      .then((projectData) => {
        if (!active) return
        setProjects(Array.isArray(projectData) ? projectData : [])
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token])

  useEffect(() => {
    let active = true
    getTasks(token, taskQueryParams)
      .then((taskData) => {
        if (!active) return
        const results = Array.isArray(taskData?.results) ? taskData.results : []
        setTasks(results)
        setTaskTotal(typeof taskData?.total === 'number' ? taskData.total : results.length)
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token, taskQueryParams, reloadCounter])

  function handleTaskCreated() {
    setReloadCounter((value) => value + 1)
  }

  function handleProjectCreated(project) {
    setProjects((current) => {
      if (current.some((existing) => existing.id === project.id)) {
        return current
      }
      return [...current, project]
    })
  }

  async function handleToggleComplete(task, completed) {
    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })

    try {
      await setTaskCompleted(token, task.id, completed)
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function toggleDeleteReveal(taskId) {
    setOpenDeleteTaskId((current) => (current === taskId ? '' : taskId))
  }

  async function handleDeleteTask(taskId) {
    setError('')
    setDeletingTaskIds((current) => {
      const next = new Set(current)
      next.add(taskId)
      return next
    })
    try {
      await deleteTask(token, taskId)
      setOpenDeleteTaskId('')
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setDeletingTaskIds((current) => {
        const next = new Set(current)
        next.delete(taskId)
        return next
      })
    }
  }

  async function handlePriorityChange(task, nextLevel) {
    const nextPriority = priorityValueFromLevel(nextLevel)
    if (task.priority === nextPriority) {
      return
    }
    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })
    try {
      await updateTask(token, task.id, { priority: nextPriority })
      setReloadCounter((value) => value + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function toggleTaskDetails(task) {
    if (expandedTaskId === task.id) {
      setExpandedTaskId('')
      setDetailsNotes('')
      setDetailsAttachments([])
      setIsAttachmentDragOver(false)
      setAttachmentPreview(null)
      return
    }
    setExpandedTaskId(task.id)
    setDetailsNotes(task.notes || '')
    setDetailsAttachments(normalizeAttachments(task.attachments))
    setIsAttachmentDragOver(false)
    setError('')
  }

  function openAttachmentPreview(attachment) {
    const previewType = attachmentPreviewType(attachment)
    if (!previewType) {
      return
    }

    setAttachmentPreview({
      name: attachment.name,
      url: attachment.url,
      previewType,
    })
  }

  function closeAttachmentPreview() {
    setAttachmentPreview(null)
  }

  function handleAttachmentTitleClick(event, attachment) {
    const previewType = attachmentPreviewType(attachment)
    if (!previewType || isModifiedLinkClick(event)) {
      return
    }
    event.preventDefault()
    openAttachmentPreview(attachment)
  }

  function handleRemoveAttachmentDraft(index) {
    setDetailsAttachments((current) => current.filter((_, currentIndex) => currentIndex !== index))
  }

  async function handleAttachmentFiles(task, files) {
    const selectedFiles = Array.from(files || [])
    if (!selectedFiles.length) {
      return
    }

    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })

    try {
      let latestAttachments = detailsAttachments
      for (const file of selectedFiles) {
        const response = await uploadTaskAttachment(token, task.id, file)
        if (Array.isArray(response?.attachments)) {
          latestAttachments = normalizeAttachments(response.attachments)
        }
      }
      setDetailsAttachments(latestAttachments)
      setTasks((current) =>
        current.map((currentTask) =>
          currentTask.id === task.id
            ? {
                ...currentTask,
                attachments: latestAttachments,
              }
            : currentTask
        )
      )
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function handleAttachmentInputChange(task, event) {
    const files = event.target.files
    if (files && files.length) {
      handleAttachmentFiles(task, files)
    }
    event.target.value = ''
  }

  function handleAttachmentDragOver(event) {
    event.preventDefault()
    setIsAttachmentDragOver(true)
  }

  function handleAttachmentDragLeave(event) {
    event.preventDefault()
    if (event.currentTarget.contains(event.relatedTarget)) {
      return
    }
    setIsAttachmentDragOver(false)
  }

  function handleAttachmentDrop(task, event) {
    event.preventDefault()
    setIsAttachmentDragOver(false)
    const files = event.dataTransfer?.files
    if (files && files.length) {
      handleAttachmentFiles(task, files)
    }
  }

  async function handleSaveTaskDetails(task) {
    setError('')
    setUpdatingTaskIds((current) => {
      const next = new Set(current)
      next.add(task.id)
      return next
    })
    try {
      const payload = {
        notes: detailsNotes,
        attachments: detailsAttachments,
      }
      await updateTask(token, task.id, payload)
      setTasks((current) =>
        current.map((currentTask) =>
          currentTask.id === task.id
            ? {
                ...currentTask,
                ...payload,
              }
            : currentTask
        )
      )
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setUpdatingTaskIds((current) => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    }
  }

  function clearDragState() {
    setDraggedTaskId('')
    setDropTarget(null)
  }

  function handleDragStart(event, taskId) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(taskId))
    setDraggedTaskId(taskId)
  }

  function handleRowDragOver(event, taskId) {
    if (!draggedTaskId || draggedTaskId === taskId) {
      return
    }
    event.preventDefault()
    const rowRect = event.currentTarget.getBoundingClientRect()
    const position = event.clientY - rowRect.top < rowRect.height / 2 ? 'before' : 'after'
    setDropTarget((current) => {
      if (current?.taskId === taskId && current.position === position) {
        return current
      }
      return { taskId, position }
    })
  }

  async function handleRowDrop(event, taskId) {
    if (!draggedTaskId || draggedTaskId === taskId) {
      clearDragState()
      return
    }
    event.preventDefault()
    const rowRect = event.currentTarget.getBoundingClientRect()
    const placement = event.clientY - rowRect.top < rowRect.height / 2 ? 'before' : 'after'
    try {
      await reorderTask(token, draggedTaskId, taskId, placement)
      setReloadCounter((value) => value + 1)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      clearDragState()
    }
  }

  function handleBodyDragOver(event) {
    if (!draggedTaskId) {
      return
    }
    if (event.target.closest('tr[data-task-id]')) {
      return
    }
    event.preventDefault()
    const lastTask = filteredTasks[filteredTasks.length - 1]
    if (lastTask) {
      setDropTarget({ taskId: lastTask.id, position: 'after' })
    }
  }

  async function handleBodyDrop(event) {
    if (!draggedTaskId) {
      return
    }
    if (event.target.closest('tr[data-task-id]')) {
      return
    }
    event.preventDefault()
    const lastTask = filteredTasks[filteredTasks.length - 1]
    if (!lastTask || lastTask.id === draggedTaskId) {
      clearDragState()
      return
    }
    try {
      await reorderTask(token, draggedTaskId, lastTask.id, 'after')
      setReloadCounter((value) => value + 1)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      clearDragState()
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>Views</h2>
        <ul className="view-list">
          <li>
            <button
              type="button"
              className={activeView.type === 'all' ? 'view-button view-button-active' : 'view-button'}
              onClick={() => setActiveView({ type: 'all' })}
            >
              All Tasks
            </button>
          </li>
          <li>
            <button
              type="button"
              className={
                activeView.type === 'area' && activeView.area === 'work'
                  ? 'view-button view-button-active'
                  : 'view-button'
              }
              onClick={() => setActiveView({ type: 'area', area: 'work' })}
            >
              Work
            </button>
            <ul className="subview-list">
              {workProjects.map((project) => (
                <li key={project.id}>
                  <button
                    type="button"
                    className={
                      activeView.type === 'project' && activeView.projectId === project.id
                        ? 'view-button view-button-sub view-button-active'
                        : 'view-button view-button-sub'
                    }
                    onClick={() => setActiveView({ type: 'project', projectId: project.id })}
                  >
                    {project.name}
                  </button>
                </li>
              ))}
            </ul>
          </li>
          <li>
            <button
              type="button"
              className={
                activeView.type === 'area' && activeView.area === 'personal'
                  ? 'view-button view-button-active'
                  : 'view-button'
              }
              onClick={() => setActiveView({ type: 'area', area: 'personal' })}
            >
              Personal
            </button>
            <ul className="subview-list">
              {personalProjects.map((project) => (
                <li key={project.id}>
                  <button
                    type="button"
                    className={
                      activeView.type === 'project' && activeView.projectId === project.id
                        ? 'view-button view-button-sub view-button-active'
                        : 'view-button view-button-sub'
                    }
                    onClick={() => setActiveView({ type: 'project', projectId: project.id })}
                  >
                    {project.name}
                  </button>
                </li>
              ))}
            </ul>
          </li>
        </ul>
        <div className="sidebar-footer">
          <label className="sidebar-toggle">
            <input
              type="checkbox"
              checked={groupByPriority}
              onChange={(e) => setGroupByPriority(e.target.checked)}
            />{' '}
            By Priority
          </label>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-main">
            <div className="search-row">
              <input placeholder="Search tasks" aria-label="Search tasks" />
              <div className="search-toggles">
                <label className="semantic-toggle">
                  <input type="checkbox" /> Semantic
                </label>
              </div>
            </div>
            <QuickAdd
              token={token}
              projects={projects}
              onTaskCreated={handleTaskCreated}
              onProjectCreated={handleProjectCreated}
              inline
            />
          </div>
          <button onClick={onLogout}>Log Out</button>
        </header>

        <section className="content">
          <h1>{activeViewLabel}</h1>
          <p>{taskCountLabel}</p>
          {error ? <p className="error-text">{error}</p> : null}
          <table className="tasks-table">
            <thead>
              <tr>
                <th className="expand-header"></th>
                <th className="drag-header"></th>
                <th>Done</th>
                <th>Title</th>
                <th>Area</th>
                <th>Project</th>
                <th>Priority</th>
                <th>Created</th>
                <th className="actions-header"></th>
              </tr>
            </thead>
            <tbody onDragOver={handleBodyDragOver} onDrop={handleBodyDrop}>
              {filteredTasks.map((task) => (
                <Fragment key={task.id}>
                  <tr
                    data-task-id={task.id}
                    className={[
                      task.status === 'done' ? 'task-row-done' : '',
                      openDeleteTaskId === task.id ? 'task-row-actions-open' : '',
                      dropTarget?.taskId === task.id && dropTarget.position === 'before'
                        ? 'task-row-drop-before'
                        : '',
                      dropTarget?.taskId === task.id && dropTarget.position === 'after'
                        ? 'task-row-drop-after'
                        : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onDragOver={(event) => handleRowDragOver(event, task.id)}
                    onDrop={(event) => handleRowDrop(event, task.id)}
                  >
                    <td className="expand-cell">
                      <div className="task-cell-content">
                        <button
                          type="button"
                          className={
                            expandedTaskId === task.id
                              ? 'task-expand-toggle task-expand-toggle-open'
                              : 'task-expand-toggle'
                          }
                          onClick={() => toggleTaskDetails(task)}
                          aria-label={
                            expandedTaskId === task.id
                              ? `Collapse details for ${task.title}`
                              : `Expand details for ${task.title}`
                          }
                        >
                          ▶
                        </button>
                      </div>
                    </td>
                    <td className="drag-cell">
                      <button
                        type="button"
                        className="task-grabber"
                        draggable
                        onDragStart={(event) => handleDragStart(event, task.id)}
                        onDragEnd={clearDragState}
                        aria-label={`Reorder ${task.title}`}
                      >
                        ⋮⋮
                      </button>
                    </td>
                    <td className="complete-cell">
                      <div className="task-cell-content">
                        <input
                          type="checkbox"
                          className="task-complete-checkbox"
                          checked={task.status === 'done'}
                          disabled={updatingTaskIds.has(task.id) || task.status === 'archived'}
                          onChange={(e) => handleToggleComplete(task, e.target.checked)}
                          aria-label={`Mark ${task.title} as complete`}
                        />
                      </div>
                    </td>
                    <td>
                      <div className="task-cell-content">{task.title}</div>
                    </td>
                    <td>
                      <div className="task-cell-content">{task.area}</div>
                    </td>
                    <td>
                      <div className="task-cell-content">
                        {task.project ? projectNameById[task.project] || 'Unknown project' : 'None'}
                      </div>
                    </td>
                    <td>
                      <div className="task-cell-content">
                        <select
                          className={`task-priority-select ${priorityClassFromLevel(
                            priorityLevelFromValue(task.priority)
                          )}`.trim()}
                          value={priorityLevelFromValue(task.priority)}
                          disabled={updatingTaskIds.has(task.id)}
                          onChange={(e) => handlePriorityChange(task, e.target.value)}
                          aria-label={`Set priority for ${task.title}`}
                        >
                          {PRIORITY_OPTIONS.map((option) => (
                            <option key={option.value || 'none'} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </td>
                    <td>
                      <div className="task-cell-content">
                        {formatCreatedTimestamp(task.created_at || task.created)}
                      </div>
                    </td>
                    <td className="task-action-cell" data-task-action-id={task.id}>
                      <button
                        type="button"
                        className="task-minus"
                        onClick={() => toggleDeleteReveal(task.id)}
                        aria-label={
                          openDeleteTaskId === task.id ? 'Hide delete action' : 'Show delete action'
                        }
                      >
                        −
                      </button>
                      <button
                        type="button"
                        className="task-delete"
                        onClick={() => handleDeleteTask(task.id)}
                        disabled={deletingTaskIds.has(task.id)}
                      >
                        {deletingTaskIds.has(task.id) ? 'Deleting...' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                  {expandedTaskId === task.id ? (
                    <tr className={task.status === 'done' ? 'task-details-row task-row-done' : 'task-details-row'}>
                      <td colSpan={9} className="task-details-cell">
                        <div className="task-details-panel">
                          <div className="task-details-section">
                            <label htmlFor={`task-notes-${task.id}`}>Notes</label>
                            <textarea
                              id={`task-notes-${task.id}`}
                              className="task-details-notes"
                              value={detailsNotes}
                              disabled={updatingTaskIds.has(task.id)}
                              onChange={(e) => setDetailsNotes(e.target.value)}
                              placeholder="Add notes, email context, or other details."
                            />
                          </div>
                          <div className="task-details-section">
                            <label>Attachments</label>
                            <div
                              className={
                                isAttachmentDragOver
                                  ? 'task-attachment-dropzone task-attachment-dropzone-active'
                                  : 'task-attachment-dropzone'
                              }
                              onDragOver={handleAttachmentDragOver}
                              onDragLeave={handleAttachmentDragLeave}
                              onDrop={(event) => handleAttachmentDrop(task, event)}
                            >
                              <p>Drag and drop files here</p>
                              <p className="task-attachment-dropzone-sub">or</p>
                              <label className="task-attachment-upload-label">
                                <input
                                  type="file"
                                  multiple
                                  disabled={updatingTaskIds.has(task.id)}
                                  onChange={(event) => handleAttachmentInputChange(task, event)}
                                />
                                Select files
                              </label>
                            </div>
                            {detailsAttachments.length ? (
                              <ul className="task-attachment-list">
                                {detailsAttachments.map((attachment, index) => {
                                  const previewType = attachmentPreviewType(attachment)
                                  return (
                                    <li key={`${attachment.url}-${index}`} className="task-attachment-item">
                                      <a
                                        className="task-attachment-link"
                                        href={attachment.url}
                                        target={previewType ? undefined : '_blank'}
                                        rel={previewType ? undefined : 'noreferrer'}
                                        onClick={(event) => handleAttachmentTitleClick(event, attachment)}
                                      >
                                        {attachment.name}
                                      </a>
                                      <div className="task-attachment-actions">
                                        {previewType ? (
                                          <button
                                            type="button"
                                            className="task-attachment-preview"
                                            onClick={() => openAttachmentPreview(attachment)}
                                            aria-label={`View ${attachment.name}`}
                                            title={`View ${attachment.name}`}
                                          >
                                            <EyeIcon />
                                          </button>
                                        ) : null}
                                        <a
                                          className="task-attachment-download"
                                          href={attachment.url}
                                          download={attachment.name}
                                          aria-label={`Download ${attachment.name}`}
                                          title={`Download ${attachment.name}`}
                                        >
                                          <DownloadIcon />
                                        </a>
                                        <button
                                          type="button"
                                          className="task-attachment-remove"
                                          disabled={updatingTaskIds.has(task.id)}
                                          onClick={() => handleRemoveAttachmentDraft(index)}
                                        >
                                          Remove
                                        </button>
                                      </div>
                                    </li>
                                  )
                                })}
                              </ul>
                            ) : (
                              <p className="task-details-empty">No attachments yet.</p>
                            )}
                          </div>
                          <div className="task-details-actions">
                            <button
                              type="button"
                              disabled={updatingTaskIds.has(task.id)}
                              onClick={() => handleSaveTaskDetails(task)}
                            >
                              {updatingTaskIds.has(task.id) ? 'Saving...' : 'Save details'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
              {!filteredTasks.length ? (
                <tr>
                  <td colSpan={9}>No tasks in this view.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </section>
      </main>
      {attachmentPreview ? (
        <div
          className="attachment-preview-backdrop"
          role="presentation"
          onClick={closeAttachmentPreview}
        >
          <div
            className="attachment-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`Preview ${attachmentPreview.name}`}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="attachment-preview-header">
              <p title={attachmentPreview.name}>{attachmentPreview.name}</p>
              <div className="attachment-preview-actions">
                <a href={attachmentPreview.url} download={attachmentPreview.name}>
                  Download
                </a>
                <button type="button" onClick={closeAttachmentPreview}>
                  Close
                </button>
              </div>
            </div>
            <div className="attachment-preview-body">
              {attachmentPreview.previewType === 'image' ? (
                <img src={attachmentPreview.url} alt={attachmentPreview.name} />
              ) : (
                <PdfCanvasViewer url={attachmentPreview.url} fileName={attachmentPreview.name} />
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function QuickAddMobile({ token }) {
  const [projects, setProjects] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getProjects(token)
      .then((projectData) => {
        if (!active) return
        setProjects(Array.isArray(projectData) ? projectData : [])
        setError('')
      })
      .catch((e) => {
        if (!active) return
        setError(e.message)
      })

    return () => {
      active = false
    }
  }, [token])

  return (
    <div className="mobile-quick-add">
      <h1>Quick Add</h1>
      {error ? <p className="error-text">{error}</p> : null}
      <QuickAdd
        token={token}
        projects={projects}
        onTaskCreated={() => {}}
        onProjectCreated={(project) =>
          setProjects((current) =>
            current.some((existing) => existing.id === project.id) ? current : [...current, project]
          )
        }
      />
    </div>
  )
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [token, setToken] = useState(localStorage.getItem(TOKEN_KEY) || '')

  useEffect(() => {
    const isMobile = window.matchMedia('(max-width: 768px)').matches
    if (token && isMobile && location.pathname === '/') {
      navigate('/quick-add', { replace: true })
    }
  }, [token, location.pathname, navigate])

  function handleLogin(accessToken) {
    localStorage.setItem(TOKEN_KEY, accessToken)
    setToken(accessToken)
    navigate('/', { replace: true })
  }

  function handleLogout() {
    localStorage.removeItem(TOKEN_KEY)
    setToken('')
    navigate('/login', { replace: true })
  }

  if (!token && location.pathname !== '/login') {
    return <Navigate to="/login" replace />
  }

  return (
    <Routes>
      <Route path="/login" element={<AuthPage onLoggedIn={handleLogin} />} />
      <Route path="/" element={<Dashboard token={token} onLogout={handleLogout} />} />
      <Route path="/quick-add" element={<QuickAddMobile token={token} />} />
    </Routes>
  )
}
