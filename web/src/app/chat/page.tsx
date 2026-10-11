"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ChatNotFound, ChatView } from "@/components/chat-view";

// A conversation is named in the address's query, not its path: the pages are exported as they are, and there is
// no page to make for each conversation there will be
function Chat() {
  const id = useSearchParams().get("id");

  return id ? <ChatView key={id} id={id} /> : <ChatNotFound />;
}

export default function ChatPage() {
  return (
    <Suspense>
      <Chat />
    </Suspense>
  );
}
