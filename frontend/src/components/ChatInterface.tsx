import { useEffect, useRef } from "react"
import { MessageSquareIcon, SendIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

function TypingDots() {
  return (
    <div className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-2 animate-bounce rounded-full bg-muted-foreground/40 motion-reduce:animate-none"
          style={{ animationDelay: `${i * 0.1}s` }}
        />
      ))}
    </div>
  )
}

export default function ChatInterface({
  repositories,
  selectedRepoId,
  setSelectedRepoId,
  chatHistory,
  chatInput,
  setChatInput,
  handleAskQuestion,
  isChatLoading,
}: any) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [chatHistory, isChatLoading])

  const activeRepos = repositories.filter(
    (r: any) => r.status === "completed" && r.is_queryable,
  )

  const lastMessage = chatHistory[chatHistory.length - 1]
  const showStandaloneDots =
    isChatLoading && lastMessage?.role !== "assistant"

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="flex h-16 flex-shrink-0 items-center gap-3 border-b bg-card px-6">
        <label className="text-sm font-medium text-muted-foreground">
          Active context
        </label>
        <Select
          value={selectedRepoId ? String(selectedRepoId) : undefined}
          onValueChange={setSelectedRepoId}
        >
          <SelectTrigger className="h-9 w-full max-w-md">
            <SelectValue placeholder="Select a repository..." />
          </SelectTrigger>
          <SelectContent>
            {activeRepos.map((repo: any) => (
              <SelectItem key={repo.id} value={String(repo.id)}>
                {repo.full_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <ScrollArea className="flex-1">
        <div className="mx-auto flex max-w-3xl flex-col gap-5 p-6">
          {chatHistory.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-24 text-center text-muted-foreground">
              <div className="flex size-14 items-center justify-center rounded-2xl bg-muted">
                <MessageSquareIcon className="size-7" />
              </div>
              <p className="text-lg font-medium text-foreground">
                Ask a question about your codebase
              </p>
              <p className="max-w-md text-sm">
                E.g., "How does the authentication flow work in this repo?"
              </p>
            </div>
          ) : (
            chatHistory.map((msg: any, idx: number) => {
              const isUser = msg.role === "user"
              const isPendingAssistant = !isUser && isChatLoading && !msg.text
              return (
                <div
                  key={idx}
                  className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-xs ${
                      isUser
                        ? "rounded-br-sm bg-primary text-primary-foreground"
                        : "rounded-bl-sm border bg-card text-card-foreground"
                    }`}
                  >
                    {isPendingAssistant ? <TypingDots /> : msg.text}
                  </div>
                </div>
              )
            })
          )}

          {showStandaloneDots && (
            <div className="flex justify-start">
              <div className="rounded-2xl rounded-bl-sm border bg-card px-4 py-3 shadow-xs">
                <TypingDots />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>

      <div className="flex-shrink-0 border-t bg-card p-4">
        <div className="relative mx-auto max-w-3xl">
          <Input
            type="text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAskQuestion()}
            placeholder={
              selectedRepoId
                ? "Ask anything about the code..."
                : "Select a repository first..."
            }
            disabled={!selectedRepoId || isChatLoading}
            className="h-11 pr-12"
          />
          <Button
            size="icon"
            onClick={handleAskQuestion}
            disabled={!selectedRepoId || isChatLoading || !chatInput.trim()}
            aria-label="Send message"
            className="absolute right-1.5 top-1.5"
          >
            <SendIcon />
          </Button>
        </div>
      </div>
    </div>
  )
}
