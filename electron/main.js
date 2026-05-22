const { app, BrowserWindow, ipcMain, Menu, dialog, shell } = require('electron');
const path = require('path');
const http = require('http');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

const DEFAULT_DEV_URL = 'http://localhost:8888';
const GEMINI_MODEL = 'gemini-2.5-flash';
const GEMINI_ENDPOINT = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;
let resolvedDevUrl = null; // set at startup; see startEmbeddedServer / NBME_ELECTRON_URL override

const BATCH_IMPORT_RUNNER = path.join(app.getAppPath(), 'tools', 'batch-import-center', 'run_pipeline_job.py');
const BATCH_IMPORT_REGISTRY = path.join(app.getAppPath(), 'tools', 'batch-import-center', 'pipeline_registry.json');
const BATCH_JOB_MANIFEST_VERSION = 'batch-import-job-v1';
const BATCH_JOB_HISTORY_VERSION = 'batch-import-job-history-v1';
const BATCH_QUEUE_VERSION = 'batch-import-queue-v1';
const activeBatchJobs = new Map();
const batchQueueWaiters = new Map();
let batchQueueRunning = false;

ipcMain.handle('nbme:ai:get-status', async () => ({
  available: true,
  provider: 'gemini',
  model: GEMINI_MODEL,
  hasApiKey: !!process.env.GEMINI_API_KEY,
  desktopMode: true
}));

function readBatchRegistry() {
  const raw = fs.readFileSync(BATCH_IMPORT_REGISTRY, 'utf8');
  return JSON.parse(raw);
}

function batchHistoryPath() {
  const dir = path.join(app.getPath('userData'), 'batch-import-center');
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, 'job-history.json');
}

function batchJobOutputRoot(jobId) {
  const outputRoot = path.join(app.getPath('userData'), 'batch-import-center', 'jobs', jobId);
  fs.mkdirSync(outputRoot, { recursive: true });
  return outputRoot;
}

function batchJobsRoot() {
  return path.join(app.getPath('userData'), 'batch-import-center', 'jobs');
}

function pathLivesUnder(rootPath, candidatePath) {
  const root = path.resolve(String(rootPath || ''));
  const candidate = path.resolve(String(candidatePath || ''));
  return candidate === root || (!path.relative(root, candidate).startsWith('..') && !path.isAbsolute(path.relative(root, candidate)));
}

function knownBatchQueueJob(jobId) {
  const cleanJobId = String(jobId || '').trim();
  if (!cleanJobId) return null;
  return readBatchQueue().jobs.find(job => job.jobId === cleanJobId) || null;
}

function knownBatchJobOutputRoot(job) {
  const outputRoot = String(job?.outputRoot || '').trim();
  if (!outputRoot || !pathLivesUnder(batchJobsRoot(), outputRoot)) return '';
  return path.resolve(outputRoot);
}

function knownBatchJobLogsPath(job) {
  const outputRoot = knownBatchJobOutputRoot(job);
  const logsPath = String(job?.logsPath || '').trim();
  if (!outputRoot || !logsPath || !pathLivesUnder(outputRoot, logsPath)) return '';
  if (path.basename(logsPath) !== 'queue-events.ndjson') return '';
  return path.resolve(logsPath);
}

function batchQueuePath() {
  const queueDir = path.join(app.getPath('userData'), 'batch-import-center', 'queue');
  fs.mkdirSync(queueDir, { recursive: true });
  return path.join(queueDir, 'jobs.json');
}

function readBatchQueue() {
  const queuePath = batchQueuePath();
  if (!fs.existsSync(queuePath)) return { schemaVersion: BATCH_QUEUE_VERSION, jobs: [] };
  try {
    const parsed = JSON.parse(fs.readFileSync(queuePath, 'utf8'));
    if (!parsed || !Array.isArray(parsed.jobs)) throw new Error('Invalid queue shape');
    return { schemaVersion: parsed.schemaVersion || BATCH_QUEUE_VERSION, jobs: parsed.jobs.filter(job => job && typeof job === 'object') };
  } catch (_) {
    return { schemaVersion: BATCH_QUEUE_VERSION, jobs: [] };
  }
}

function writeBatchQueue(queue) {
  const queuePath = batchQueuePath();
  const tmpPath = `${queuePath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(queue, null, 2), 'utf8');
  fs.renameSync(tmpPath, queuePath);
}

function updateBatchQueueJob(jobId, patch) {
  const queue = readBatchQueue();
  const idx = queue.jobs.findIndex(job => job.jobId === jobId);
  if (idx < 0) return null;
  const existing = queue.jobs[idx];
  const cleanPatch = Object.fromEntries(Object.entries(patch || {}).filter(([, value]) => value !== undefined));
  const updated = {
    ...existing,
    ...cleanPatch,
    progress: cleanPatch.progress && typeof cleanPatch.progress === 'object' ? cleanPatch.progress : (existing.progress || {}),
    outputPaths: Array.isArray(cleanPatch.outputPaths) ? cleanPatch.outputPaths : (existing.outputPaths || []),
    warnings: Array.isArray(cleanPatch.warnings) ? cleanPatch.warnings : (existing.warnings || []),
    errors: Array.isArray(cleanPatch.errors) ? cleanPatch.errors : (existing.errors || []),
    updatedAt: new Date().toISOString()
  };
  queue.jobs[idx] = updated;
  writeBatchQueue(queue);
  emitBatchQueueChanged();
  return updated;
}

function persistBatchQueueJob(job) {
  const queue = readBatchQueue();
  const jobs = queue.jobs.filter(existing => existing.jobId !== job.jobId);
  jobs.push(job);
  writeBatchQueue({ schemaVersion: BATCH_QUEUE_VERSION, jobs });
  emitBatchQueueChanged();
  return job;
}

function removeBatchQueueJob(jobId) {
  const queue = readBatchQueue();
  const job = queue.jobs.find(item => item.jobId === jobId);
  if (!job) return null;
  if (!['completed', 'failed', 'canceled', 'interrupted'].includes(job.status)) return false;
  writeBatchQueue({
    schemaVersion: queue.schemaVersion || BATCH_QUEUE_VERSION,
    jobs: queue.jobs.filter(item => item.jobId !== jobId)
  });
  emitBatchQueueChanged();
  return job;
}

function emitBatchQueueChanged() {
  const payload = { queue: readBatchQueue() };
  BrowserWindow.getAllWindows().forEach(win => {
    if (!win.isDestroyed()) win.webContents.send('nbme:batch-import:queue-changed', payload);
  });
}

function appendBatchLog(logsPath, eventPayload) {
  try {
    fs.mkdirSync(path.dirname(logsPath), { recursive: true });
    fs.appendFileSync(logsPath, `${JSON.stringify(eventPayload)}\n`, 'utf8');
  } catch (_) {}
}

function writeBatchCompletionReport(outputRoot, report) {
  try {
    const reportPath = path.join(outputRoot, 'completion-report.json');
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, JSON.stringify(report || {}, null, 2), 'utf8');
    return reportPath;
  } catch (_) {
    return null;
  }
}

function readBatchJobHistory() {
  const historyPath = batchHistoryPath();
  if (!fs.existsSync(historyPath)) return { schemaVersion: BATCH_JOB_HISTORY_VERSION, jobs: [] };
  try {
    const parsed = JSON.parse(fs.readFileSync(historyPath, 'utf8'));
    if (!parsed || !Array.isArray(parsed.jobs)) throw new Error('Invalid history shape');
    return {
      schemaVersion: parsed.schemaVersion || BATCH_JOB_HISTORY_VERSION,
      jobs: parsed.jobs.filter(job => job && typeof job === 'object')
    };
  } catch (_) {
    return { schemaVersion: BATCH_JOB_HISTORY_VERSION, jobs: [] };
  }
}

function writeBatchJobHistory(history) {
  const historyPath = batchHistoryPath();
  const tmpPath = `${historyPath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(history, null, 2), 'utf8');
  fs.renameSync(tmpPath, historyPath);
}

function persistBatchJobRecord(record) {
  const history = readBatchJobHistory();
  const jobs = history.jobs.filter(job => job.jobId !== record.jobId);
  jobs.unshift(record);
  writeBatchJobHistory({
    schemaVersion: BATCH_JOB_HISTORY_VERSION,
    jobs: jobs
      .sort((a, b) => String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')))
      .slice(0, 100)
  });
  return record;
}

function updateBatchJobRecord(jobId, patch) {
  const history = readBatchJobHistory();
  const existing = history.jobs.find(job => job.jobId === jobId);
  if (!existing) return null;
  const cleanPatch = Object.fromEntries(
    Object.entries(patch || {}).filter(([, value]) => value !== undefined)
  );
  const updated = {
    ...existing,
    ...cleanPatch,
    warnings: Array.isArray(cleanPatch.warnings) ? cleanPatch.warnings : (existing.warnings || []),
    errors: Array.isArray(cleanPatch.errors) ? cleanPatch.errors : (existing.errors || []),
    outputPaths: Array.isArray(cleanPatch.outputPaths) ? cleanPatch.outputPaths : (existing.outputPaths || []),
    updatedAt: new Date().toISOString()
  };
  return persistBatchJobRecord(updated);
}

function reconcileStaleBatchJobs() {
  const history = readBatchJobHistory();
  let changed = false;
  const jobs = history.jobs.map(job => {
    if (job.status === 'running') {
      changed = true;
      return {
        ...job,
        status: 'failed',
        completedAt: job.completedAt || new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        errors: [...(job.errors || []), 'The app closed before this job reported completion.']
      };
    }
    return job;
  });
  if (changed) writeBatchJobHistory({ schemaVersion: BATCH_JOB_HISTORY_VERSION, jobs });
}

function reconcileInterruptedBatchQueue() {
  const queue = readBatchQueue();
  let changed = false;
  const now = new Date().toISOString();
  queue.jobs = queue.jobs.map(job => {
    if (job.status !== 'running' || activeBatchJobs.has(job.jobId)) return job;
    changed = true;
    return {
      ...job,
      status: 'interrupted',
      finishedAt: job.finishedAt || now,
      updatedAt: now,
      errors: [...(job.errors || []), 'The app closed before this queued job reported completion.']
    };
  });
  if (changed) writeBatchQueue(queue);
}

function initialBatchJobRecord(manifest, source, manifestPath) {
  const now = new Date().toISOString();
  return {
    jobId: manifest.jobId,
    status: 'queued',
    createdAt: manifest.createdAt || now,
    startedAt: null,
    completedAt: null,
    updatedAt: now,
    sourceType: manifest.sourceType,
    sourceLabel: source?.label || manifest.sourceType,
    dryRun: !!manifest.dryRun,
    targetFolderId: manifest.destination?.folderId || '',
    targetTestName: manifest.destination?.testName || '',
    inputPaths: (manifest.inputs || []).map(item => item.path).filter(Boolean),
    outputRoot: manifest.outputRoot || '',
    manifestPath,
    runtimeSeconds: null,
    currentStage: 'preflight',
    outputPaths: [],
    warnings: [],
    errors: [],
    report: null,
    importedTestId: null,
    importedTestName: null
  };
}

function readEnvLocal() {
  const envPath = path.join(app.getAppPath(), '.env.local');
  if (!fs.existsSync(envPath) || !fs.statSync(envPath).isFile()) return {};
  const parsed = {};
  const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    parsed[match[1]] = value;
  }
  return parsed;
}

function batchEnvFromLocalSources() {
  const env = { ...process.env };
  if (!env.GEMINI_API_KEY) {
    const localEnv = readEnvLocal();
    if (localEnv.GEMINI_API_KEY) env.GEMINI_API_KEY = localEnv.GEMINI_API_KEY;
  }
  return env;
}

async function shellHasGeminiApiKey() {
  return await new Promise(resolve => {
    const proc = spawn('/bin/zsh', ['-lc', 'source ~/.zshrc >/dev/null 2>&1 || true; test -n "$GEMINI_API_KEY"'], {
      cwd: app.getAppPath(),
      env: process.env,
      stdio: ['ignore', 'ignore', 'ignore']
    });
    proc.on('error', () => resolve(false));
    proc.on('close', code => resolve(code === 0));
  });
}

async function resolveBatchEnvironment(requiresGemini) {
  const env = batchEnvFromLocalSources();
  if (!requiresGemini || env.GEMINI_API_KEY) {
    return { ok: true, env, useLoginShell: false };
  }
  if (await shellHasGeminiApiKey()) {
    return { ok: true, env: process.env, useLoginShell: true };
  }
  return safeError(
    'BATCH_GEMINI_KEY_UNAVAILABLE',
    'GEMINI_API_KEY is not available to the Electron batch process.'
  );
}

function sanitizeBatchJobPayload(payload, source) {
  const sourceType = String(payload?.sourceType || '').trim();
  const inputPaths = Array.isArray(payload?.inputPaths) ? payload.inputPaths : [];
  const folderId = String(payload?.destination?.folderId || '').trim();
  const testName = String(payload?.destination?.testName || '').trim();
  const existingOutputValidation = payload?.existingOutputValidation === true;
  const dryRun = payload?.dryRun !== false;
  const executePipeline = payload?.executePipeline === true;

  if (!sourceType) throw new Error('sourceType is required.');
  if (!inputPaths.length) throw new Error('At least one input file is required.');

  const jobId = `batch-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    manifestVersion: BATCH_JOB_MANIFEST_VERSION,
    jobId,
    sourceType,
    inputs: inputPaths.map(inputPath => ({ path: String(inputPath || '').trim() })).filter(item => item.path),
    requiresGemini: existingOutputValidation ? false : !!source?.requiresGemini,
    dryRun,
    executePipeline,
    existingOutputValidation,
    destination: { folderId, testName },
    outputRoot: batchJobOutputRoot(jobId),
    createdAt: new Date().toISOString()
  };
}

function writeBatchManifest(manifest) {
  const jobDir = manifest.outputRoot || path.join(os.tmpdir(), 'nbme-batch-import-center');
  fs.mkdirSync(jobDir, { recursive: true });
  const manifestPath = path.join(jobDir, `${manifest.jobId}.json`);
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
  return manifestPath;
}

function queueJobFromManifest(manifest, source, payload, manifestPath) {
  const now = new Date().toISOString();
  const outputRoot = manifest.outputRoot || batchJobOutputRoot(manifest.jobId);
  return {
    jobId: manifest.jobId,
    batchId: String(payload?.batchId || '').trim() || null,
    sourceType: manifest.sourceType,
    sourceLabel: source?.label || manifest.sourceType,
    inputFiles: (manifest.inputs || []).map(item => ({ path: item.path })),
    destinationFolderId: manifest.destination?.folderId || '',
    testName: manifest.destination?.testName || '',
    runMode: String(payload?.runMode || '').trim(),
    dryRun: !!manifest.dryRun,
    executePipeline: !!manifest.executePipeline,
    existingOutputValidation: !!manifest.existingOutputValidation,
    requiresGemini: !!manifest.requiresGemini,
    status: 'pending',
    progress: { phase: 'pending', message: 'Waiting in queue.', updatedAt: now },
    createdAt: manifest.createdAt || now,
    updatedAt: now,
    startedAt: null,
    finishedAt: null,
    outputRoot,
    outputPaths: [],
    warnings: [],
    errors: [],
    reportPath: null,
    logsPath: path.join(outputRoot, 'queue-events.ndjson'),
    importedTestId: null,
    manifestPath,
    manifest,
    lastHeartbeatAt: null
  };
}

ipcMain.handle('nbme:batch-import:get-registry', async () => {
  try {
    return { ok: true, registry: readBatchRegistry() };
  } catch (err) {
    return safeError('BATCH_REGISTRY_UNAVAILABLE', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:get-history', async () => {
  try {
    reconcileStaleBatchJobs();
    return { ok: true, history: readBatchJobHistory() };
  } catch (err) {
    return safeError('BATCH_HISTORY_UNAVAILABLE', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:get-queue', async () => {
  try {
    reconcileInterruptedBatchQueue();
    scheduleBatchQueue();
    return { ok: true, queue: readBatchQueue() };
  } catch (err) {
    return safeError('BATCH_QUEUE_UNAVAILABLE', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:read-queue-job-logs', async (_event, payload) => {
  try {
    const job = knownBatchQueueJob(payload?.jobId);
    if (!job) return safeError('BATCH_QUEUE_JOB_NOT_FOUND', 'Queued batch job was not found.');
    const logsPath = knownBatchJobLogsPath(job);
    if (!logsPath) return safeError('BATCH_QUEUE_LOG_REJECTED', 'Job log path is not a known durable queue log.');
    if (!fs.existsSync(logsPath)) return { ok: true, jobId: job.jobId, logsPath, lines: [] };
    if (fs.lstatSync(logsPath).isSymbolicLink() || !fs.statSync(logsPath).isFile()) {
      return safeError('BATCH_QUEUE_LOG_MISSING', 'Job log file was not found.');
    }
    const requestedLimit = Number(payload?.limit || 80);
    const limit = Math.max(1, Math.min(200, Number.isFinite(requestedLimit) ? requestedLimit : 80));
    const lines = fs.readFileSync(logsPath, 'utf8')
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-limit);
    return { ok: true, jobId: job.jobId, logsPath, lines };
  } catch (err) {
    return safeError('BATCH_QUEUE_LOG_READ_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:open-queue-job-artifacts', async (_event, payload) => {
  try {
    const job = knownBatchQueueJob(payload?.jobId);
    if (!job) return safeError('BATCH_QUEUE_JOB_NOT_FOUND', 'Queued batch job was not found.');
    const outputRoot = knownBatchJobOutputRoot(job);
    if (!outputRoot) return safeError('BATCH_QUEUE_OUTPUT_REJECTED', 'Job output folder is not under the durable Batch Import jobs root.');
    if (!fs.existsSync(outputRoot) || !fs.statSync(outputRoot).isDirectory()) {
      return safeError('BATCH_QUEUE_OUTPUT_MISSING', 'Job output folder was not found.');
    }
    const openError = await shell.openPath(outputRoot);
    if (openError) return safeError('BATCH_QUEUE_OUTPUT_OPEN_FAILED', openError);
    return { ok: true, jobId: job.jobId, outputRoot };
  } catch (err) {
    return safeError('BATCH_QUEUE_OUTPUT_OPEN_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:remove-queue-job', async (_event, payload) => {
  try {
    const jobId = String(payload?.jobId || '').trim();
    if (!jobId) return safeError('BATCH_JOB_ID_REQUIRED', 'jobId is required.');
    const removed = removeBatchQueueJob(jobId);
    if (removed === null) return safeError('BATCH_QUEUE_JOB_NOT_FOUND', 'Queued batch job was not found.');
    if (removed === false) {
      return safeError('BATCH_QUEUE_JOB_NOT_REMOVABLE', 'Only completed, failed, canceled, or interrupted jobs can be removed from the queue list.');
    }
    return { ok: true, job: removed, queue: readBatchQueue() };
  } catch (err) {
    return safeError('BATCH_QUEUE_REMOVE_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:update-job-report', async (_event, payload) => {
  try {
    const jobId = String(payload?.jobId || '').trim();
    if (!jobId) return safeError('BATCH_JOB_ID_REQUIRED', 'jobId is required.');
    const report = payload?.report && typeof payload.report === 'object' ? payload.report : {};
    const updated = updateBatchJobRecord(jobId, {
      status: report.status || payload?.status || undefined,
      completedAt: report.completedAt || undefined,
      runtimeSeconds: Number.isFinite(report.runtimeSeconds) ? report.runtimeSeconds : undefined,
      outputPaths: Array.isArray(report.outputPaths) ? report.outputPaths : undefined,
      warnings: Array.isArray(report.warnings) ? report.warnings : undefined,
      errors: Array.isArray(report.errors) ? report.errors : undefined,
      importedTestId: report.importedTestId || null,
      importedTestName: report.importedTestName || null,
      report
    });
    if (!updated) return safeError('BATCH_JOB_NOT_FOUND', 'Job history record was not found.');
    updateBatchQueueJob(jobId, {
      status: report.status || payload?.status || undefined,
      finishedAt: report.completedAt || undefined,
      outputPaths: Array.isArray(report.outputPaths) ? report.outputPaths : undefined,
      warnings: Array.isArray(report.warnings) ? report.warnings : undefined,
      errors: Array.isArray(report.errors) ? report.errors : undefined,
      importedTestId: report.importedTestId || undefined,
      report
    });
    return { ok: true, job: updated };
  } catch (err) {
    return safeError('BATCH_HISTORY_UPDATE_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:cancel-job', async (_event, payload) => {
  try {
    const jobId = String(payload?.jobId || '').trim();
    if (!jobId) return safeError('BATCH_JOB_ID_REQUIRED', 'jobId is required.');
    const active = activeBatchJobs.get(jobId);
    if (!active) {
      return safeError('BATCH_JOB_NOT_RUNNING', 'No running batch job was found for that id.');
    }
    active.cancelled = true;
    active.cancelledAt = new Date().toISOString();
    updateBatchJobRecord(jobId, {
      status: 'cancelled',
      completedAt: active.cancelledAt,
      errors: [],
      warnings: [...(active.warnings || []), 'Job cancelled by user.']
    });
    updateBatchQueueJob(jobId, {
      status: 'canceled',
      finishedAt: active.cancelledAt,
      warnings: [...(active.warnings || []), 'Job canceled by user.']
    });
    if (active.proc?.pid) {
      try {
        process.kill(-active.proc.pid, 'SIGTERM');
      } catch (_) {
        try { active.proc.kill('SIGTERM'); } catch (__) {}
      }
      active.killTimer = setTimeout(() => {
        if (active.proc && active.proc.exitCode === null) {
          try { process.kill(-active.proc.pid, 'SIGKILL'); } catch (_) {}
        }
      }, 5000);
    }
    return { ok: true, jobId, status: 'canceled' };
  } catch (err) {
    return safeError('BATCH_CANCEL_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:retry-queue-job', async (_event, payload) => {
  try {
    const jobId = String(payload?.jobId || '').trim();
    const job = readBatchQueue().jobs.find(item => item.jobId === jobId);
    if (!job) return safeError('BATCH_JOB_NOT_FOUND', 'Queued batch job was not found.');
    if (!['failed', 'interrupted', 'canceled', 'needs_review'].includes(job.status)) {
      return safeError('BATCH_JOB_NOT_RETRYABLE', 'Only failed, interrupted, canceled, or needs-review jobs can be retried.');
    }
    const updated = updateBatchQueueJob(jobId, {
      status: 'pending',
      startedAt: null,
      finishedAt: null,
      progress: { phase: 'pending', message: 'Retry queued.', updatedAt: new Date().toISOString() },
      errors: []
    });
    scheduleBatchQueue();
    return { ok: true, job: updated };
  } catch (err) {
    return safeError('BATCH_RETRY_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:select-files', async (_event, payload) => {
  try {
    const sourceType = String(payload?.sourceType || '').trim();
    if (!sourceType) return safeError('BATCH_SOURCE_REQUIRED', 'Choose a source type first.');
    const registry = readBatchRegistry();
    const source = registry.sources?.[sourceType];
    if (!source || source.status !== 'active') {
      return safeError('BATCH_SOURCE_UNKNOWN', `Source type is not registered: ${sourceType}`);
    }
    const existingOutputValidation = payload?.existingOutputValidation === true;
    const extensions = existingOutputValidation
      ? ['json']
      : Array.isArray(source.inputExtensions)
      ? source.inputExtensions.map(ext => String(ext).replace(/^\./, '').trim()).filter(Boolean)
      : [];
    const result = await dialog.showOpenDialog({
      title: existingOutputValidation ? 'Select existing app-ready JSON output' : `Select ${source.label || sourceType} file`,
      properties: source.allowDirectories && !existingOutputValidation
        ? ['openFile', 'openDirectory', 'multiSelections']
        : ['openFile', 'multiSelections'],
      filters: extensions.length
        ? [{ name: existingOutputValidation ? 'App-ready JSON' : (source.label || sourceType), extensions }, { name: 'All Files', extensions: ['*'] }]
        : [{ name: 'All Files', extensions: ['*'] }]
    });
    if (result.canceled) return { ok: true, canceled: true, filePaths: [] };
    return { ok: true, canceled: false, filePaths: result.filePaths || [] };
  } catch (err) {
    return safeError('BATCH_FILE_PICKER_FAILED', err.message || String(err));
  }
});

function enqueueBatchPayload(payload) {
  let manifest;
  let manifestPath;
  const sourceType = String(payload?.sourceType || '').trim();
  const registry = readBatchRegistry();
  const source = registry.sources?.[sourceType];
  if (!source || source.status !== 'active') {
    throw new Error(`Source type is not registered: ${sourceType}`);
  }
  manifest = sanitizeBatchJobPayload(payload, source);
  manifestPath = writeBatchManifest(manifest);
  persistBatchJobRecord(initialBatchJobRecord(manifest, source, manifestPath));
  return persistBatchQueueJob(queueJobFromManifest(manifest, source, payload, manifestPath));
}

ipcMain.handle('nbme:batch-import:enqueue-jobs', async (_event, payload) => {
  try {
    const payloads = Array.isArray(payload?.jobs) ? payload.jobs : [payload];
    const jobs = payloads.map(item => enqueueBatchPayload(item));
    scheduleBatchQueue();
    return { ok: true, jobs, queue: readBatchQueue() };
  } catch (err) {
    return safeError('BATCH_QUEUE_ENQUEUE_FAILED', err.message || String(err));
  }
});

ipcMain.handle('nbme:batch-import:launch-job', async (_event, payload) => {
  try {
    const job = enqueueBatchPayload(payload);
    const result = new Promise(resolve => batchQueueWaiters.set(job.jobId, resolve));
    scheduleBatchQueue();
    return await result;
  } catch (err) {
    return safeError('BATCH_JOB_INVALID', err.message || String(err));
  }
});

async function scheduleBatchQueue() {
  if (batchQueueRunning || activeBatchJobs.size) return;
  batchQueueRunning = true;
  try {
    while (!activeBatchJobs.size) {
      const next = readBatchQueue().jobs.find(job => job.status === 'pending');
      if (!next) break;
      await runQueuedBatchJob(next);
    }
  } finally {
    batchQueueRunning = false;
  }
}

async function runQueuedBatchJob(job) {
  let batchEnvironment;
  let manifest = job.manifest;
  const registry = readBatchRegistry();
  const source = registry.sources?.[job.sourceType];
  if (!source || !manifest) {
    settleBatchQueueWaiter(job.jobId, finishQueuedBatchFailure(job, 'Queued job is missing its source or manifest.'));
    return;
  }
  try {
    const dryRunRequiresGemini = !!source.dryRunRequiresGemini;
    if (manifest.requiresGemini && (!manifest.dryRun || dryRunRequiresGemini)) {
      batchEnvironment = await resolveBatchEnvironment(true);
      if (!batchEnvironment.ok) {
        settleBatchQueueWaiter(job.jobId, finishQueuedBatchFailure(job, batchEnvironment.message));
        return;
      }
    } else {
      batchEnvironment = await resolveBatchEnvironment(false);
    }
  } catch (err) {
    settleBatchQueueWaiter(job.jobId, finishQueuedBatchFailure(job, err.message || String(err)));
    return;
  }

  return await new Promise(resolve => {
    const manifestPath = job.manifestPath || writeBatchManifest(manifest);
    const warnings = [];
    const errors = [];
    const launchedAt = Date.now();
    updateBatchQueueJob(job.jobId, {
      status: 'running',
      startedAt: new Date().toISOString(),
      manifestPath,
      progress: { phase: 'preflight', message: 'Batch runner starting.', updatedAt: new Date().toISOString() }
    });
    updateBatchJobRecord(job.jobId, { status: 'running', startedAt: new Date().toISOString() });
    const sendProgress = eventPayload => {
      const enriched = { jobId: manifest.jobId, ...eventPayload };
      appendBatchLog(job.logsPath, enriched);
      if (enriched.type === 'stage_start' && enriched.stage) {
        updateBatchJobRecord(manifest.jobId, { currentStage: enriched.stage });
      }
      if (enriched.type === 'stage_start' || enriched.type === 'pipeline_progress' || enriched.type === 'stage_heartbeat' || enriched.type === 'log') {
        updateBatchQueueJob(manifest.jobId, {
          progress: {
            phase: enriched.stage || enriched.phase || enriched.stageLabel || enriched.type,
            message: enriched.message || enriched.stageLabel || enriched.type,
            updatedAt: enriched.timestamp || new Date().toISOString()
          },
          lastHeartbeatAt: enriched.timestamp || new Date().toISOString()
        });
      }
      if (enriched.type === 'warning' || enriched.type === 'cache_summary') {
        const message = enriched.message || enriched.warning;
        if (message) warnings.push(String(message));
      }
      if (enriched.type === 'error' || enriched.type === 'stage_failed') {
        const message = enriched.message || enriched.error || enriched.failureReason;
        if (message) errors.push(String(message));
      }
      BrowserWindow.getAllWindows().forEach(win => {
        if (!win.isDestroyed()) win.webContents.send('nbme:batch-import:progress', enriched);
      });
    };

    const childEnv = batchEnvironment?.env || process.env;
    const useLoginShell = !!batchEnvironment?.useLoginShell;
    const command = useLoginShell ? '/bin/zsh' : 'python3';
    const args = useLoginShell
      ? ['-lc', 'source ~/.zshrc >/dev/null 2>&1 || true; exec "$@"', 'nbme-batch-python', 'python3', BATCH_IMPORT_RUNNER, manifestPath]
      : [BATCH_IMPORT_RUNNER, manifestPath];
    const proc = spawn(command, args, {
      cwd: app.getAppPath(),
      env: childEnv,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: true
    });
    activeBatchJobs.set(manifest.jobId, { proc, manifest, manifestPath, warnings, errors, cancelled: false, killTimer: null });

    let stdoutBuffer = '';
    let stderrBuffer = '';
    let finalEvent = null;
    function consumeLine(line, streamName) {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed.type === 'job_complete') finalEvent = parsed;
        sendProgress(parsed);
      } catch (_) {
        sendProgress({ type: 'log', stream: streamName, message: trimmed, timestamp: new Date().toISOString() });
      }
    }
    proc.stdout.on('data', chunk => {
      stdoutBuffer += chunk.toString();
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() || '';
      lines.forEach(line => consumeLine(line, 'stdout'));
    });
    proc.stderr.on('data', chunk => {
      stderrBuffer += chunk.toString();
      const lines = stderrBuffer.split(/\r?\n/);
      stderrBuffer = lines.pop() || '';
      lines.forEach(line => consumeLine(line, 'stderr'));
    });
    proc.on('error', err => {
      activeBatchJobs.delete(manifest.jobId);
      const result = finishQueuedBatchFailure(job, err.message || String(err), launchedAt);
      settleBatchQueueWaiter(job.jobId, result);
      resolve();
    });
    proc.on('close', (code, signal) => {
      consumeLine(stdoutBuffer, 'stdout');
      consumeLine(stderrBuffer, 'stderr');
      const active = activeBatchJobs.get(manifest.jobId);
      if (active?.killTimer) clearTimeout(active.killTimer);
      activeBatchJobs.delete(manifest.jobId);
      const wasCancelled = !!active?.cancelled;
      const runtimeSeconds = Math.round((Date.now() - launchedAt) / 100) / 10;
      const ok = !wasCancelled && code === 0 && (!finalEvent || finalEvent.ok !== false);
      const report = finalEvent?.report && typeof finalEvent.report === 'object' ? finalEvent.report : {};
      const outputPaths = Array.isArray(finalEvent?.outputs) ? finalEvent.outputs : [];
      const fallbackMessage = signal ? `Batch job exited with signal ${signal}.` : `Batch job exited with code ${code}.`;
      const finalErrors = wasCancelled ? [] : (errors.length ? errors : (ok ? [] : [finalEvent?.error || fallbackMessage]));
      const status = wasCancelled ? 'canceled' : (ok ? (report.status === 'needs_review' ? 'needs_review' : 'completed') : 'failed');
      const finalReport = { ...report, status, runtimeSeconds, outputPaths, warnings, errors: finalErrors };
      const reportPath = writeBatchCompletionReport(job.outputRoot, finalReport);
      const finishedAt = new Date().toISOString();
      updateBatchJobRecord(manifest.jobId, {
        status,
        completedAt: finishedAt,
        runtimeSeconds,
        currentStage: status === 'completed' ? 'completed' : report.stage || null,
        outputPaths,
        reportPath,
        warnings: wasCancelled ? [...warnings, 'Job canceled by user.'] : warnings,
        errors: finalErrors,
        report: finalReport
      });
      updateBatchQueueJob(manifest.jobId, {
        status,
        finishedAt,
        outputPaths,
        reportPath,
        warnings: wasCancelled ? [...warnings, 'Job canceled by user.'] : warnings,
        errors: finalErrors,
        report: finalReport,
        progress: { phase: status, message: status === 'completed' ? 'Batch job completed.' : (finalErrors[0] || status), updatedAt: finishedAt }
      });
      const result = {
        ok,
        cancelled: wasCancelled,
        exitCode: code,
        signal,
        manifestPath,
        manifest,
        outputs: outputPaths,
        progress: [],
        report,
        errorCode: ok ? null : (wasCancelled ? 'BATCH_JOB_CANCELLED' : 'BATCH_JOB_FAILED'),
        message: ok ? null : (wasCancelled ? 'Batch job canceled.' : (finalEvent?.error || fallbackMessage))
      };
      settleBatchQueueWaiter(job.jobId, result);
      resolve();
    });
  });
}

function finishQueuedBatchFailure(job, message, launchedAt = Date.now()) {
  const finishedAt = new Date().toISOString();
  const errors = [String(message || 'Queued batch job failed.')];
  updateBatchJobRecord(job.jobId, {
    status: 'failed',
    completedAt: finishedAt,
    runtimeSeconds: Math.round((Date.now() - launchedAt) / 100) / 10,
    errors
  });
  updateBatchQueueJob(job.jobId, {
    status: 'failed',
    finishedAt,
    errors,
    progress: { phase: 'failed', message: errors[0], updatedAt: finishedAt }
  });
  return safeError('BATCH_JOB_FAILED', errors[0]);
}

function settleBatchQueueWaiter(jobId, result) {
  const waiter = batchQueueWaiters.get(jobId);
  if (!waiter) return;
  batchQueueWaiters.delete(jobId);
  waiter(result);
}

ipcMain.handle('nbme:batch-import:read-output-json', async (_event, outputPath) => {
  try {
    const resolved = path.resolve(String(outputPath || ''));
    if (!resolved.endsWith('_app_ready.json')) {
      return safeError('BATCH_OUTPUT_REJECTED', 'Only *_app_ready.json outputs can be read for auto-import.');
    }
    if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
      return safeError('BATCH_OUTPUT_MISSING', 'Output file was not found.');
    }
    return {
      ok: true,
      path: resolved,
      text: fs.readFileSync(resolved, 'utf8')
    };
  } catch (err) {
    return safeError('BATCH_OUTPUT_READ_FAILED', err.message || String(err));
  }
});

function safeError(errorCode, message) {
  return { ok: false, errorCode, message };
}

function clampText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function normalizeStringArray(value, maxItems = 12) {
  if (!Array.isArray(value)) return [];
  return value.map(v => clampText(v, 160)).filter(Boolean).slice(0, maxItems);
}

function sanitizeDraftInput(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const draft = payload.draft && typeof payload.draft === 'object' ? payload.draft : null;
  const concept = payload.concept && typeof payload.concept === 'object' ? payload.concept : null;
  if (!draft || !concept) return null;

  const sourceBlockIds = normalizeStringArray(draft.sourceBlockIds || concept.sourceBlockIds, 20);
  return {
    draft: {
      draftId: clampText(draft.draftId, 80),
      stem: clampText(draft.stem, 1600),
      choices: Array.isArray(draft.choices) ? draft.choices.slice(0, 5).map(choice => ({
        label: clampText(choice.label || choice.l, 2),
        text: clampText(choice.text || choice.t, 320)
      })) : [],
      correctAnswer: clampText(draft.correctAnswer, 2),
      teachingPoint: clampText(draft.teachingPoint, 700),
      warnings: normalizeStringArray(draft.warnings, 12)
    },
    concept: {
      conceptId: clampText(concept.conceptId || draft.sourceConceptId || draft.conceptId, 80),
      topic: clampText(concept.topic, 220),
      testedFact: clampText(concept.testedFact, 1600),
      sourceSnippet: clampText(concept.sourceSnippet || payload.sourceSnippet, 1200),
      confidence: Number.isFinite(concept.confidence) ? concept.confidence : null,
      warnings: normalizeStringArray(concept.warnings, 12)
    },
    sourceMeta: {
      sourceName: clampText(payload.sourceMeta?.sourceName, 220),
      sourceHash: clampText(payload.sourceMeta?.sourceHash, 96)
    },
    sourceBlockIds
  };
}

function buildRefinementPrompt(input) {
  return [
    'You refine deterministic UWorld notes question scaffolds into Step 2/NBME-style multiple choice question drafts.',
    'Return strict JSON only. Do not include markdown fences or explanatory text outside JSON.',
    'Use only the supplied source note and concept. Do not invent unsupported facts. Do not copy commercial question-bank wording.',
    'If the source is insufficient, still return the JSON schema, set needsReview true, lower confidence, and explain the limitation in warnings.',
    'Produce exactly five answer choices labeled A, B, C, D, and E. Include one correct answer and concise rationales for all choices.',
    'This output is preview-only and requires review before use.',
    '',
    'Required JSON schema:',
    JSON.stringify({
      stem: 'string',
      choices: [
        { label: 'A', text: 'string' },
        { label: 'B', text: 'string' },
        { label: 'C', text: 'string' },
        { label: 'D', text: 'string' },
        { label: 'E', text: 'string' }
      ],
      correctAnswer: 'A',
      teachingPoint: 'string',
      rationales: { A: 'string', B: 'string', C: 'string', D: 'string', E: 'string' },
      confidence: 0.5,
      needsReview: true,
      warnings: ['string']
    }),
    '',
    'Input:',
    JSON.stringify(input)
  ].join('\n');
}

function extractGeminiJson(data) {
  const text = data?.candidates?.[0]?.content?.parts
    ?.map(part => part.text || '')
    .join('')
    .trim();
  if (!text) throw new SyntaxError('empty model response');

  // Attempt 1: strip leading/trailing markdown fences and parse directly.
  const fenceStripped = text
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim();
  try {
    return JSON.parse(fenceStripped);
  } catch (_) {}

  // Attempt 2: locate the first top-level JSON object by brace scanning.
  // Tracks string/escape state so inner braces inside string values are ignored.
  const start = text.indexOf('{');
  if (start !== -1) {
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let i = start; i < text.length; i++) {
      const ch = text[i];
      if (escape) { escape = false; continue; }
      if (ch === '\\' && inString) { escape = true; continue; }
      if (ch === '"') { inString = !inString; continue; }
      if (inString) continue;
      if (ch === '{') depth++;
      else if (ch === '}') {
        depth--;
        if (depth === 0) {
          return JSON.parse(text.slice(start, i + 1));
        }
      }
    }
  }

  throw new SyntaxError('no valid JSON object found in model response');
}

function validateRefinedDraft(raw, input) {
  if (!raw || typeof raw !== 'object') throw new Error('response is not an object');
  const labels = ['A', 'B', 'C', 'D', 'E'];
  const choices = Array.isArray(raw.choices) ? raw.choices : [];
  if (choices.length !== 5) throw new Error('expected exactly five choices');

  const normalizedChoices = choices.map((choice, idx) => {
    const label = clampText(choice?.label, 2).toUpperCase();
    const text = clampText(choice?.text, 600);
    if (label !== labels[idx]) throw new Error('choice labels must be A through E in order');
    if (!text) throw new Error('choice text cannot be empty');
    return { label, text };
  });

  const stem = clampText(raw.stem, 2800);
  const teachingPoint = clampText(raw.teachingPoint, 1000);
  const correctAnswer = clampText(raw.correctAnswer, 2).toUpperCase();
  const rationales = raw.rationales && typeof raw.rationales === 'object' ? raw.rationales : {};
  if (stem.length < 20) throw new Error('stem is too short');
  if (teachingPoint.length < 8) throw new Error('teaching point is too short');
  if (!labels.includes(correctAnswer)) throw new Error('correct answer must be A through E');

  const normalizedRationales = {};
  labels.forEach(label => {
    const rationale = clampText(rationales[label], 700);
    if (!rationale) throw new Error(`missing rationale ${label}`);
    normalizedRationales[label] = rationale;
  });

  const warnings = normalizeStringArray(raw.warnings, 12);
  if (!warnings.includes('requires review before use')) warnings.push('requires review before use');

  return {
    refinedDraftId: `refined-${input.draft.draftId || Date.now().toString(36)}`,
    sourceDraftId: input.draft.draftId,
    sourceConceptId: input.concept.conceptId,
    sourceBlockIds: input.sourceBlockIds.slice(),
    sourceName: input.sourceMeta.sourceName,
    sourceHash: input.sourceMeta.sourceHash,
    stem,
    choices: normalizedChoices,
    correctAnswer,
    teachingPoint,
    rationales: normalizedRationales,
    confidence: Math.max(0, Math.min(1, Number.isFinite(raw.confidence) ? raw.confidence : 0.35)),
    needsReview: raw.needsReview !== false || warnings.length > 0,
    warnings,
    model: GEMINI_MODEL,
    generationMethod: 'electron-gemini-uworld-draft-refinement-v1',
    createdAt: new Date().toISOString()
  };
}

ipcMain.handle('nbme:ai:refine-uworld-draft', async (_event, payload) => {
  const apiKey = ((payload?.apiKey || '').trim()) || process.env.GEMINI_API_KEY || '';
  if (!apiKey) return safeError('NO_API_KEY', 'Gemini API key is not configured. Enter it in Settings.');

  const input = sanitizeDraftInput(payload);
  if (!input || !input.draft.draftId || !input.concept.conceptId) {
    return safeError('MODEL_RESPONSE_INVALID', 'Draft refinement input is incomplete.');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(GEMINI_ENDPOINT, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey
      },
      body: JSON.stringify({
        contents: [{ role: 'user', parts: [{ text: buildRefinementPrompt(input) }] }],
        generationConfig: {
          responseMimeType: 'application/json',
          temperature: 0.25,
          maxOutputTokens: 2200
        }
      })
    });

    if (response.status === 429) return safeError('RATE_LIMITED', 'Gemini rate limit reached. Try again later.');
    if (!response.ok) return safeError('NETWORK_ERROR', 'Gemini request failed before a valid response was returned.');

    const data = await response.json();

    let parsed;
    try {
      parsed = extractGeminiJson(data);
    } catch (parseErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response could not be parsed as JSON: ${parseErr.message}`);
    }

    let refinedDraft;
    try {
      refinedDraft = validateRefinedDraft(parsed, input);
    } catch (schemaErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response failed schema validation: ${schemaErr.message}`);
    }

    return { ok: true, refinedDraft };
  } catch (err) {
    if (err?.name === 'AbortError') return safeError('TIMEOUT', 'Gemini request timed out.');
    if (err instanceof TypeError) return safeError('NETWORK_ERROR', 'Gemini request failed because the network request could not be completed.');
    return safeError('MODEL_RESPONSE_INVALID', 'Gemini response handling failed unexpectedly.');
  } finally {
    clearTimeout(timeout);
  }
});

// ── Divine draft refinement — Gemini IPC ─────────────────────────────────────
// Refines a teaching cluster into a Step 2/NBME-style clinical vignette question.
// Gemini identifies the testable medical fact from clusterSummary.
// The app sends cleaned teaching clusters only; Gemini extracts the medical fact itself.
// sourceContext is capped at 300 chars and used only for coherence/copy detection.

// Podcast/coaching register patterns that must not appear in Gemini-generated stems.
// Reproduced here (cannot import from renderer) — kept in sync with renderer DIVINE_VOICE_MARKERS.
const DIVINE_STEM_VOICE_MARKERS = [
  /\byou need to\b/i,
  /\bI think\b/i,
  /\bremember\b/i,
  /\bdon'?t forget\b/i,
  /\bhigh[\s-]yield\b/i,
  /\bboards?\b/i,
  /\bpodcast\b/i,
  /\bI want you to\b/i,
  /\bthey give you\b/i
];

// Sanitize and clamp all renderer-supplied fields before they enter the prompt.
// Returns null on any structural failure — caller must treat null as invalid input.
function sanitizeDivineDraftInput(payload) {
  if (!payload || typeof payload !== 'object') return null;

  // clusterSummary is the primary medical source — required, trimmed, clamped ≤400 chars.
  const clusterSummary = clampText(payload.clusterSummary, 400);
  if (clusterSummary.length < 20) return null;

  const conceptType = clampText(payload.conceptType, 80);

  // variantType is optional; accepted as-is if present.
  const variantType = (payload.variantType != null) ? clampText(payload.variantType, 60) : null;

  // sourceContext is optional, hard-capped at 300 chars (coherence/copy detection only).
  const sourceContext = clampText(payload.sourceContext, 300);

  // sourceMeta — draftId and clusterId are required for provenance construction.
  const meta = (payload.sourceMeta && typeof payload.sourceMeta === 'object') ? payload.sourceMeta : {};
  const sourceMeta = {
    draftId:    clampText(meta.draftId,    80),
    clusterId:  clampText(meta.clusterId,  80),
    sourceName: clampText(meta.sourceName, 220),
    sourceHash: clampText(meta.sourceHash,  96)
  };
  if (!sourceMeta.draftId || !sourceMeta.clusterId) return null;

  // provenance — build from renderer-supplied fields; none are trusted blindly.
  const prov = (payload.provenance && typeof payload.provenance === 'object') ? payload.provenance : {};
  const tsRaw = prov.timestampRange;
  const provenance = {
    sourceSegmentIds:   normalizeStringArray(prov.sourceSegmentIds, 12),
    originalLineRanges: Array.isArray(prov.originalLineRanges) ? prov.originalLineRanges.slice(0, 12) : [],
    cleanedLineRanges:  Array.isArray(prov.cleanedLineRanges)  ? prov.cleanedLineRanges.slice(0, 12)  : [],
    timestampRanges:    Array.isArray(prov.timestampRanges)    ? prov.timestampRanges.slice(0, 12)    : [],
    timestampRange:     (tsRaw && typeof tsRaw === 'object')
                        ? { start: clampText(tsRaw.start, 20), end: clampText(tsRaw.end, 20) }
                        : null
  };

  return { conceptType, clusterSummary, sourceContext, variantType, sourceMeta, provenance };
}

// Build the Gemini prompt. clusterSummary is the sole medical source.
// Gemini extracts the testable fact itself — no hardcoded diagnostic criteria.
// sourceContext is appended last, labelled "do not copy", for coherence verification only.
function buildDivineRefinementPrompt(input) {
  const lines = [
    'You are a medical education question writer. Generate a Step 2/NBME-style clinical vignette multiple-choice question.',
    'Return strict JSON only. Do not include markdown fences or explanatory text outside JSON.',
    '',
    'CRITICAL RULES — follow exactly:',
    '1. PRIMARY INPUT is the clusterSummary below. First identify the single most testable medical fact it contains.',
    '   Record that fact as extractedTestableFact in your response.',
    '2. Choose the most accurate questionType from this exact list:',
    '   timeline-criterion | diagnostic-distinction | mechanism | management |',
    '   risk-factor | contraindication | clinical-application | other',
    '3. sourceContext is provenance only — do NOT copy, paraphrase, or echo any of its wording into the question.',
    '4. Forbidden podcast/coaching language in stem and choices:',
    '   remember, high yield, boards, you need to know, they give you,',
    '   I think, I want you to, don\'t forget, podcast voice.',
    '5. Write a concise but realistic clinical vignette: patient demographics, presenting symptoms,',
    '   relevant history, labs or imaging if needed, then the question.',
    '6. Generate exactly five answer choices labeled A through E. One best answer only.',
    '7. Choices must be clinically plausible, mutually exclusive, and not lifted from sourceContext.',
    '8. No transcript phrasing reuse. No coaching language. No "all of the above".',
    '9. If source material is insufficient, still produce all five choices, set needsReview true,',
    '   lower confidence, and explain in warnings.',
    '10. This output is preview-only and requires expert review before clinical use.',
    '',
    'Required JSON schema (return exactly this structure):',
    JSON.stringify({
      extractedTestableFact: 'string — the specific medical fact identified as testable',
      questionType: 'timeline-criterion | diagnostic-distinction | mechanism | management | risk-factor | contraindication | clinical-application | other',
      stem: 'string',
      choices: [
        { label: 'A', text: 'string' },
        { label: 'B', text: 'string' },
        { label: 'C', text: 'string' },
        { label: 'D', text: 'string' },
        { label: 'E', text: 'string' }
      ],
      correctAnswer: 'A',
      teachingPoint: 'string',
      rationales: { A: 'string', B: 'string', C: 'string', D: 'string', E: 'string' },
      confidence: 0.85,
      needsReview: false,
      warnings: []
    }),
    ''
  ];

  if (input.conceptType) lines.push(`Concept type: ${input.conceptType}`);
  if (input.variantType) lines.push(`Variant hint: ${input.variantType}`);

  lines.push(
    '',
    'Teaching cluster (primary medical input — extract the testable fact from this):',
    input.clusterSummary,
    '',
    'Source context — provenance only, do NOT copy or echo any phrasing:',
    input.sourceContext || '(none)'
  );

  return lines.join('\n');
}

// Detect verbatim overlap between Gemini output and the source context.
// Returns true if any 8-consecutive-word sequence from sourceContext appears in text.
// Prevents Gemini from lifting podcast transcript phrasing into the question stem or choices.
function divineCopyOverlapDetected(text, sourceContext) {
  if (!sourceContext || !text) return false;
  const srcWords  = sourceContext.toLowerCase().split(/\s+/).filter(Boolean);
  const testWords = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (srcWords.length < 8 || testWords.length < 8) return false;
  const testStr = testWords.join(' ');
  const WINDOW  = 8;
  for (let i = 0; i <= srcWords.length - WINDOW; i++) {
    const ngram = srcWords.slice(i, i + WINDOW).join(' ');
    if (testStr.includes(ngram)) return true;
  }
  return false;
}

// Validate and normalize Gemini's raw JSON object.
// All provenance fields are constructed from sanitized input — nothing is trusted from Gemini.
// Throws with a specific human-readable message on any failure.
function validateDivineRefinedDraft(raw, input) {
  if (!raw || typeof raw !== 'object') throw new Error('response is not an object');

  const labels = ['A', 'B', 'C', 'D', 'E'];

  // 1. extractedTestableFact — Gemini-identified testable fact; must be substantive.
  const extractedTestableFact = clampText(raw.extractedTestableFact, 600).trim();
  if (extractedTestableFact.length < 10) {
    throw new Error(`extractedTestableFact too short (${extractedTestableFact.length} chars, need ≥10)`);
  }

  // 2. questionType — must be nonempty; clamped to 80 chars.
  const questionType = clampText(raw.questionType, 80);
  if (!questionType) throw new Error('questionType is missing or empty');

  // 3. stem — clinical vignette; must be substantive.
  const stem = clampText(raw.stem, 3000);
  if (stem.length < 40) throw new Error(`stem too short (${stem.length} chars, need ≥40)`);

  // 4-5. choices — exactly 5, labels A through E in order.
  const rawChoices = Array.isArray(raw.choices) ? raw.choices : [];
  if (rawChoices.length !== 5) throw new Error(`expected exactly 5 choices, got ${rawChoices.length}`);
  const normalizedChoices = rawChoices.map((choice, idx) => {
    const label = clampText(choice?.label, 2).toUpperCase();
    const text  = clampText(choice?.text, 600);
    if (label !== labels[idx]) throw new Error(`choice label must be ${labels[idx]}, got "${label}"`);
    if (!text) throw new Error(`choice text is empty for label ${labels[idx]}`);
    return { label, text };
  });

  // 6. correctAnswer — must be one of A–E.
  const correctAnswer = clampText(raw.correctAnswer, 2).toUpperCase();
  if (!labels.includes(correctAnswer)) throw new Error('correctAnswer must be A through E');

  // 7. teachingPoint — must be a substantive clinical statement.
  const teachingPoint = clampText(raw.teachingPoint, 1200);
  if (teachingPoint.length < 20) throw new Error(`teachingPoint too short (${teachingPoint.length} chars, need ≥20)`);

  // 8. rationales — all five labels required and nonempty.
  const rawRationales = (raw.rationales && typeof raw.rationales === 'object') ? raw.rationales : {};
  const normalizedRationales = {};
  for (const label of labels) {
    const rationale = clampText(rawRationales[label], 700);
    if (!rationale) throw new Error(`missing rationale for choice ${label}`);
    normalizedRationales[label] = rationale;
  }

  // 9. anti-copy: no 8-word verbatim overlap between sourceContext and stem or any choice.
  const sourceContext = input.sourceContext || '';
  if (divineCopyOverlapDetected(stem, sourceContext)) {
    throw new Error('stem contains verbatim overlap with source context (≥8 consecutive words)');
  }
  for (const { label, text } of normalizedChoices) {
    if (divineCopyOverlapDetected(text, sourceContext)) {
      throw new Error(`choice ${label} contains verbatim overlap with source context (≥8 consecutive words)`);
    }
  }

  // 10. no podcast/coaching voice in the stem.
  for (const marker of DIVINE_STEM_VOICE_MARKERS) {
    if (marker.test(stem)) {
      throw new Error(`stem contains podcast/coaching language matching /${marker.source}/`);
    }
  }

  // 11. warnings — normalise; always append the review sentinel.
  const warnings = normalizeStringArray(raw.warnings, 12);
  if (!warnings.includes('requires review before use')) warnings.push('requires review before use');

  // 12. Assemble result. All provenance comes from sanitized input — never from Gemini output.
  return {
    extractedTestableFact,
    questionType,
    refinedDraftId: `divine-refined-${input.sourceMeta.draftId}-${Date.now().toString(36)}`,
    draftId:        input.sourceMeta.draftId,
    clusterId:      input.sourceMeta.clusterId,
    sourceName:     input.sourceMeta.sourceName,
    sourceHash:     input.sourceMeta.sourceHash,
    provenance:     input.provenance,
    stem,
    choices:        normalizedChoices,
    correctAnswer,
    teachingPoint,
    rationales:     normalizedRationales,
    confidence:     Math.max(0, Math.min(1, Number.isFinite(raw.confidence) ? raw.confidence : 0.35)),
    needsReview:    raw.needsReview !== false || warnings.length > 1,
    warnings,
    model:             GEMINI_MODEL,
    generationMethod:  'electron-gemini-divine-cluster-v2',
    createdAt:         new Date().toISOString()
  };
}

ipcMain.handle('nbme:ai:refine-divine-draft', async (_event, payload) => {
  const apiKey = ((payload?.apiKey || '').trim()) || process.env.GEMINI_API_KEY || '';
  if (!apiKey) return safeError('NO_API_KEY', 'Gemini API key is not configured. Enter it in Settings.');

  const input = sanitizeDivineDraftInput(payload);
  if (!input) {
    return safeError('MODEL_RESPONSE_INVALID', 'Divine draft refinement input is incomplete or malformed.');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(GEMINI_ENDPOINT, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey
      },
      body: JSON.stringify({
        contents: [{ role: 'user', parts: [{ text: buildDivineRefinementPrompt(input) }] }],
        generationConfig: {
          responseMimeType: 'application/json',
          temperature: 0.30,
          maxOutputTokens: 2400
        }
      })
    });

    if (response.status === 429) return safeError('RATE_LIMITED', 'Gemini rate limit reached. Try again later.');
    if (!response.ok) return safeError('NETWORK_ERROR', 'Gemini request failed before a valid response was returned.');

    const data = await response.json();

    let parsed;
    try {
      parsed = extractGeminiJson(data);
    } catch (parseErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response could not be parsed as JSON: ${parseErr.message}`);
    }

    let refinedDraft;
    try {
      refinedDraft = validateDivineRefinedDraft(parsed, input);
    } catch (schemaErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response failed validation: ${schemaErr.message}`);
    }

    return { ok: true, refinedDraft };
  } catch (err) {
    if (err?.name === 'AbortError') return safeError('TIMEOUT', 'Gemini request timed out.');
    if (err instanceof TypeError) return safeError('NETWORK_ERROR', 'Gemini request failed because the network request could not be completed.');
    return safeError('MODEL_RESPONSE_INVALID', 'Gemini response handling failed unexpectedly.');
  } finally {
    clearTimeout(timeout);
  }
});

// ── Embedded static file server ──────────────────────────────────────────────
// Serves index.html (and local static assets) from the project root over HTTP so
// that Google Drive OAuth, PDF.js workers, and Tesseract workers can all use an
// approved HTTP/HTTPS origin. Binds to 127.0.0.1 only. Not used when
// NBME_ELECTRON_URL is set.

const PROJECT_ROOT = path.resolve(__dirname, '..');

const MIME = {
  '.html':  'text/html; charset=utf-8',
  '.js':    'application/javascript; charset=utf-8',
  '.css':   'text/css; charset=utf-8',
  '.json':  'application/json; charset=utf-8',
  '.png':   'image/png',
  '.jpg':   'image/jpeg',
  '.jpeg':  'image/jpeg',
  '.webp':  'image/webp',
  '.svg':   'image/svg+xml',
  '.pdf':   'application/pdf',
  '.woff':  'font/woff',
  '.woff2': 'font/woff2',
  '.wasm':  'application/wasm',
  '.txt':   'text/plain; charset=utf-8'
};

const LOCAL_FIGURE_MIME = {
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp'
};

function resolveLocalPath(rawUrl) {
  try {
    const clean = decodeURIComponent((rawUrl || '/').split('?')[0].split('#')[0]) || '/';
    const rel = clean.startsWith('/') ? clean : '/' + clean;
    const abs = path.resolve(PROJECT_ROOT, '.' + rel);
    // Reject any path that escapes the project root (path traversal guard).
    if (abs !== PROJECT_ROOT && !abs.startsWith(PROJECT_ROOT + path.sep)) return null;
    return abs;
  } catch (_) {
    return null;
  }
}

function serveIndexHtml(res, reason) {
  const indexPath = path.join(PROJECT_ROOT, 'index.html');
  console.log('[NBME ROUTE /] Serving index from:', indexPath, reason ? `(reason: ${reason})` : '');
  try {
    const indexHtml = fs.readFileSync(indexPath, 'utf8');
    console.log('[NBME INDEX MARKER PRESENT]', indexHtml.includes('APP_BUILD_MARKER'));
  } catch(e) {
    console.log('[NBME INDEX MARKER PRESENT] error reading file synchronously:', e.message);
  }
  fs.readFile(indexPath, (err, data) => {
    if (err) { res.writeHead(500); res.end(); return; }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}

function resolveExternalFigurePath(rawPath) {
  const raw = String(rawPath || '').trim();
  if (!raw) return null;
  try {
    if (/^file:/i.test(raw)) return decodeURIComponent(new URL(raw).pathname);
    return path.resolve(raw);
  } catch (_) {
    return null;
  }
}

function serveExternalFigure(req, res) {
  let parsed;
  try {
    parsed = new URL(req.url, 'http://127.0.0.1');
  } catch (_) {
    res.writeHead(400); res.end(); return;
  }
  const localPath = resolveExternalFigurePath(parsed.searchParams.get('path'));
  if (!localPath) { res.writeHead(400); res.end(); return; }
  const ext = path.extname(localPath).toLowerCase();
  const contentType = LOCAL_FIGURE_MIME[ext];
  if (!contentType) { res.writeHead(403); res.end(); return; }
  fs.stat(localPath, (err, stat) => {
    if (err || !stat.isFile()) { res.writeHead(404); res.end(); return; }
    fs.readFile(localPath, (readErr, data) => {
      if (readErr) { res.writeHead(500); res.end(); return; }
      res.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'no-cache' });
      res.end(data);
    });
  });
}

function createRequestHandler() {
  return function (req, res) {
    console.log('[NBME REQUEST]', req.method, req.url);
    if ((req.url || '').startsWith('/__nbme_local_figure__')) {
      return serveExternalFigure(req, res);
    }
    const localPath = resolveLocalPath(req.url);
    if (!localPath) return serveIndexHtml(res, 'bad URL'); // bad URL → SPA fallback

    fs.stat(localPath, (err, stat) => {
      if (err || !stat.isFile()) return serveIndexHtml(res, `not found: ${localPath}`); // not found → SPA fallback

      const ext = path.extname(localPath).toLowerCase();
      const contentType = MIME[ext];
      if (!contentType) { res.writeHead(403); res.end(); return; } // unknown type → deny

      fs.readFile(localPath, (readErr, data) => {
        if (readErr) { res.writeHead(500); res.end(); return; }
        res.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'no-cache' });
        res.end(data);
      });
    });
  };
}

function tryListenOnPort(handler, port) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.once('error', () => { server.close(); resolve(null); });
    server.once('listening', () => resolve(server));
    server.listen(port, '127.0.0.1');
  });
}

async function startEmbeddedServer() {
  const handler = createRequestHandler();
  for (const port of [8888, 8080]) {
    const server = await tryListenOnPort(handler, port);
    if (server) return server;
  }
  // Fall back to an OS-assigned port (port 0).
  const server = await tryListenOnPort(handler, 0);
  if (!server) throw new Error('[NBME] Embedded HTTP server failed to bind on any port.');
  return server;
}

let _embeddedServer = null;

// ─────────────────────────────────────────────────────────────────────────────

// ── Application menu ─────────────────────────────────────────────────────────
// Provides Cmd+R / Cmd+Shift+R reload shortcuts and a standard macOS menu bar.
// Without this, Electron uses its default menu which has no reload shortcut and
// may not wire Cmd+Q correctly when the window is in a custom state.
function buildAppMenu(win) {
  return Menu.buildFromTemplate([
    {
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'View',
      submenu: [
        {
          label: 'Reload',
          accelerator: 'CmdOrCtrl+R',
          click: () => {
            const w = BrowserWindow.getFocusedWindow();
            if (w) w.webContents.reload();
          }
        },
        {
          label: 'Hard Reload',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: () => {
            const w = BrowserWindow.getFocusedWindow();
            if (w) w.webContents.reloadIgnoringCache();
          }
        },
        { type: 'separator' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        { role: 'close' }
      ]
    }
  ]);
}

// Main process boundary:
// Owns Electron window lifecycle and loading the existing HTTP-served app only.
// App logic, parser/OCR/render behavior, Drive, and storage remain in index.html.
// AI status is owned here so future Gemini calls can remain outside the renderer.
function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false
    }
  });

  win.once('ready-to-show', () => {
    win.show();
  });

  // The renderer's Drive IIFE registers a beforeunload handler that calls
  // e.preventDefault() while a Drive sync is pending.  In Electron this fires
  // will-prevent-unload on the webContents; without overriding it the window
  // close silently does nothing — the red X appears to do nothing at all.
  // We override it here and handle state flushing ourselves in the close handler.
  win.webContents.on('will-prevent-unload', (e) => {
    e.preventDefault(); // allow the unload — flush already handled below
  });

  // Flush renderer state then close.  Two-pass pattern: first pass defers the
  // close to run the flush; second pass (isClosing=true) lets it proceed.
  let isClosing = false;
  win.on('close', async (e) => {
    if (isClosing) return;
    e.preventDefault();
    isClosing = true;

    try {
      // Give the renderer up to 3 s to flush Drive sync and localStorage.
      // saveGoogleDriveNow() is a no-op when no Drive token is present.
      await Promise.race([
        win.webContents.executeJavaScript(`(async () => {
          try {
            if (typeof window.saveGoogleDriveNow === 'function') {
              await window.saveGoogleDriveNow();
            }
            if (typeof DB !== 'undefined' && typeof DB.save === 'function') {
              DB.save();
            }
          } catch (_) {}
          return 'done';
        })()`),
        new Promise(resolve => setTimeout(resolve, 3000))
      ]);
    } catch (err) {
      console.error('[NBME] State flush failed on close:', err.message);
    }

    win.close(); // second pass — isClosing is true, close proceeds
  });

  win.loadURL(resolvedDevUrl);
}

app.whenReady().then(async () => {
  reconcileInterruptedBatchQueue();
  if (process.env.NBME_ELECTRON_URL) {
    resolvedDevUrl = process.env.NBME_ELECTRON_URL;
    console.log('[NBME] Using external URL override:', resolvedDevUrl);
  } else {
    _embeddedServer = await startEmbeddedServer();
    const { port } = _embeddedServer.address();
    resolvedDevUrl = `http://localhost:${port}`;
    console.log('[NBME] Embedded server listening at:', resolvedDevUrl);
  }

  createWindow();
  scheduleBatchQueue();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// Always quit when all windows are closed.  This is a single-window app;
// the standard macOS "keep app alive in dock" behavior is not appropriate here.
// Without this, the embedded HTTP server keeps the process alive after the
// window is closed, requiring a force-quit.
app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  if (_embeddedServer) {
    _embeddedServer.close();
    _embeddedServer = null;
  }
});

// Set menu after app is ready (called from whenReady chain above via createWindow,
// but Menu.setApplicationMenu can be called any time — set it once on first window).
app.on('browser-window-created', (_e, win) => {
  Menu.setApplicationMenu(buildAppMenu(win));
});
