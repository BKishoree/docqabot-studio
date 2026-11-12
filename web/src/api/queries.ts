// TanStack Query wiring: keys, hooks, polling rules (DESIGN 6.3) and global error side effects.
import {
  MutationCache,
  QueryCache,
  QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { api, ApiError } from './client'
import type { AskResponse, ConversationDetail, ConversationSummary, DocumentItem, ListResponse } from './types'

export const keys = {
  health: ['health'] as const,
  config: ['config'] as const,
  documents: ['documents'] as const,
  conversations: ['conversations'] as const,
  conversation: (id: string) => ['conversation', id] as const,
}

// ---- 401 handling: a tiny external store the shell reads.
let authRequired = false
const authListeners = new Set<() => void>()
export function setAuthRequired(value: boolean) {
  if (authRequired === value) return
  authRequired = value
  authListeners.forEach((l) => l())
}
export function useAuthRequired(): boolean {
  return useSyncExternalStore(
    (l) => {
      authListeners.add(l)
      return () => authListeners.delete(l)
    },
    () => authRequired,
    () => false,
  )
}

/** Shared reaction to any failed call: 401 notice, health refresh after 502/503. */
function onApiError(client: QueryClient, error: unknown) {
  if (!(error instanceof ApiError)) return
  if (error.status === 401) setAuthRequired(true)
  if (error.status === 502 || error.status === 503 || error.status === 0) {
    api
      .health(true)
      .then((h) => client.setQueryData(keys.health, h))
      .catch(() => undefined)
  }
}

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (e) => onApiError(client, e) }),
    mutationCache: new MutationCache({ onError: (e) => onApiError(client, e) }),
    defaultOptions: {
      queries: {
        retry: (count, error) =>
          error instanceof ApiError && [401, 404, 422].includes(error.status) ? false : count < 1,
        refetchOnWindowFocus: true,
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  })
  return client
}

// ---- Queries

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => api.health(),
    refetchInterval: (q) => (q.state.data?.components.database.status === 'unavailable' || q.state.error ? 5_000 : 30_000),
    refetchIntervalInBackground: false,
    retry: false,
  })
}

export function useConfig() {
  return useQuery({ queryKey: keys.config, queryFn: api.config, staleTime: Infinity })
}

export function useDocuments() {
  return useQuery({
    queryKey: keys.documents,
    queryFn: api.listDocuments,
    refetchInterval: (q) => (q.state.data?.items.some((d) => d.status === 'processing') ? 2_000 : false),
  })
}

export function useConversations() {
  return useQuery({ queryKey: keys.conversations, queryFn: () => api.listConversations(50, 0) })
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: keys.conversation(id ?? ''),
    queryFn: () => api.getConversation(id!),
    enabled: Boolean(id),
  })
}

// ---- Mutations

export function useUploadDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadDocument(file),
    onSuccess: (doc) => {
      qc.setQueryData<ListResponse<DocumentItem>>(keys.documents, (old) =>
        old ? { items: [doc, ...old.items.filter((d) => d.id !== doc.id)], total: old.total + 1 } : old,
      )
      void qc.invalidateQueries({ queryKey: keys.documents })
    },
  })
}

export function useDeleteDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.deleteDocument(id),
    onSuccess: (_v, id) => {
      qc.setQueryData<ListResponse<DocumentItem>>(keys.documents, (old) =>
        old ? { items: old.items.filter((d) => d.id !== id), total: Math.max(0, old.total - 1) } : old,
      )
      void qc.invalidateQueries({ queryKey: keys.documents })
      // Old answers now show the source as removed.
      void qc.invalidateQueries({ queryKey: ['conversation'] })
    },
  })
}

export function useRenameConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.renameConversation(id, title),
    onSuccess: (conv) => {
      patchSummary(qc, conv)
      qc.setQueryData<ConversationDetail>(keys.conversation(conv.id), (old) => (old ? { ...old, ...conv } : old))
    },
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_v, id) => {
      qc.setQueryData<ListResponse<ConversationSummary>>(keys.conversations, (old) =>
        old ? { items: old.items.filter((c) => c.id !== id), total: Math.max(0, old.total - 1) } : old,
      )
      qc.removeQueries({ queryKey: keys.conversation(id) })
    },
  })
}

/**
 * Ask a question. With no conversation id, the conversation is created first
 * (DESIGN 4.5: created at the moment the first question is sent).
 */
export function useAsk() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ conversationId, question }: { conversationId?: string; question: string }) => {
      let id = conversationId
      if (!id) {
        const created = await api.createConversation()
        id = created.id
        patchSummary(qc, created)
      }
      try {
        return await api.ask(id, question)
      } catch (error) {
        if (error instanceof ApiError) (error as ApiError & { conversationId?: string }).conversationId = id
        throw error
      }
    },
    onSuccess: (res: AskResponse) => {
      patchSummary(qc, res.conversation)
      qc.setQueryData<ConversationDetail>(keys.conversation(res.conversation.id), (old) => ({
        ...(old ?? { messages: [] }),
        ...res.conversation,
        messages: [...(old?.messages ?? []), res.user_message, res.assistant_message],
      }))
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.conversations })
    },
  })
}

function patchSummary(qc: QueryClient, conv: ConversationSummary) {
  qc.setQueryData<ListResponse<ConversationSummary>>(keys.conversations, (old) => {
    if (!old) return old
    const rest = old.items.filter((c) => c.id !== conv.id)
    const existed = rest.length !== old.items.length
    return { items: [conv, ...rest], total: existed ? old.total : old.total + 1 }
  })
}
