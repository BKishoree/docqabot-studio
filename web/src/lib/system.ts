// Derived system state used by the shell, composer and library.
import { useDocuments, useHealth } from '../api/queries'
import type { Health, OpenAIStatus } from '../api/types'

export interface Block {
  code: 'database_unavailable' | 'openai_not_configured' | 'no_ready_documents'
  message: string
}

export interface SystemState {
  health: Health | undefined
  healthFailed: boolean
  mode: 'live' | 'demo' | undefined
  openai: OpenAIStatus | undefined
  databaseDown: boolean
  readyCount: number
  processingCount: number
  failedCount: number
  documentsLoaded: boolean
  /** Why asking is not possible right now, or null. */
  askBlock: Block | null
  /** Why uploading is not possible right now, or null. */
  uploadBlock: Block | null
}

export function useSystem(): SystemState {
  const health = useHealth()
  const docs = useDocuments()
  const h = health.data
  const items = docs.data?.items ?? []
  const readyCount = items.filter((d) => d.status === 'ready').length
  const processingCount = items.filter((d) => d.status === 'processing').length
  const failedCount = items.filter((d) => d.status === 'failed').length
  const databaseDown = h?.components.database.status === 'unavailable'
  const openai = h?.components.openai.status

  let askBlock: Block | null = null
  let uploadBlock: Block | null = null
  if (databaseDown) {
    const b: Block = {
      code: 'database_unavailable',
      message: 'The database is unavailable, so nothing can be asked or uploaded. This page reconnects by itself.',
    }
    askBlock = b
    uploadBlock = b
  } else if (openai === 'not_configured') {
    const b: Block = {
      code: 'openai_not_configured',
      message: 'OpenAI is not configured. Add OPENAI_API_KEY to the server settings, or start the app in demo mode.',
    }
    askBlock = b
    uploadBlock = b
  } else if (docs.isSuccess && readyCount === 0) {
    askBlock = {
      code: 'no_ready_documents',
      message:
        processingCount > 0
          ? 'Your documents are still being indexed. You can ask as soon as one is ready.'
          : 'Upload at least one document in the Library and wait until it is ready.',
    }
  }

  return {
    health: h,
    healthFailed: health.isError,
    mode: h?.mode,
    openai,
    databaseDown,
    readyCount,
    processingCount,
    failedCount,
    documentsLoaded: docs.isSuccess,
    askBlock,
    uploadBlock,
  }
}
