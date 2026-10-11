"use client";

import { Children, isValidElement, memo, useState, type ComponentProps, type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "@/components/code";
import { useFileUrl } from "@/components/chat-files";
import { localPath } from "@/lib/files";
import { linkKind } from "@/lib/links";
import { cn } from "@/lib/utils";

const LINK = "font-medium text-brand underline decoration-brand/40 underline-offset-2 hover:decoration-brand";

function textOf(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(textOf).join("");

  return "";
}

// What an answer links to is shown as a link only where it goes somewhere that is safe to go: a web address or an
// email, which open apart from this page, a place in this page, or a file of the conversation. Anything else, such as
// a script's address, is left as its text.
function Link({ href, children }: ComponentProps<"a">) {
  const fileAddress = useFileUrl();
  if (!href) return <>{children}</>;

  const file = localPath(href);
  const address = file === null ? null : fileAddress(file);
  if (address !== null) {
    return (
      <a href={address} target="_blank" rel="noopener noreferrer" className={LINK}>
        {children}
      </a>
    );
  }
  const kind = linkKind(href);
  if (kind === "web") {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={LINK}>
        {children}
      </a>
    );
  }
  if (kind === "place") {
    return (
      <a href={href} className={LINK}>
        {children}
      </a>
    );
  }

  return <>{children}</>;
}

// A figure is shown where it is one of the conversation's files. One from elsewhere is not fetched, since that would
// tell whoever runs that address that this answer was read, and what it would show is not what the lab made.
function Figure({ src, alt }: ComponentProps<"img">) {
  const fileAddress = useFileUrl();
  const [missing, setMissing] = useState(false);
  const file = typeof src === "string" ? localPath(src) : null;
  const address = file === null ? null : fileAddress(file);
  if (address === null) {
    return <span className="italic text-muted-foreground">[{alt || "An image"}, from elsewhere, is not shown]</span>;
  }
  if (missing) {
    return <span className="italic text-muted-foreground">[{alt || "An image"} is not one of the files]</span>;
  }

  return (
    <a href={address} target="_blank" rel="noopener noreferrer" className="inline-block max-w-full">
      {/* The file is the conversation's own, from the server's API, so there is nothing for next/image to optimize */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={address}
        alt={alt ?? ""}
        loading="lazy"
        onError={() => setMissing(true)}
        className="max-h-96 max-w-full rounded-lg border border-border"
      />
    </a>
  );
}

function Block({ children }: { children?: ReactNode }) {
  const code = Children.toArray(children).find((child): child is ReactElement<{ className?: string; children?: ReactNode }> =>
    isValidElement(child),
  );
  const language = /language-([\w+#-]+)/.exec(code?.props.className ?? "")?.[1] ?? null;

  return <CodeBlock code={textOf(code?.props.children).replace(/\n$/, "")} language={language} />;
}

const components: Components = {
  a: Link,
  img: Figure,
  pre: Block,
  code: ({ className, children }) => (
    <code className={cn("rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]", className)}>{children}</code>
  ),
  h1: ({ children }) => <h2 className="mt-3 text-xl font-semibold tracking-tight">{children}</h2>,
  h2: ({ children }) => <h3 className="mt-3 text-lg font-semibold tracking-tight">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-2 text-base font-semibold">{children}</h4>,
  h4: ({ children }) => <h5 className="mt-2 text-[15px] font-semibold">{children}</h5>,
  ul: ({ children }) => <ul className="flex list-disc flex-col gap-1.5 pl-6 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="flex list-decimal flex-col gap-1.5 pl-6 marker:text-muted-foreground">{children}</ol>,
  blockquote: ({ children }) => (
    <blockquote className="flex flex-col gap-3 border-l-2 border-border pl-4 text-muted-foreground">{children}</blockquote>
  ),
  hr: () => <hr className="my-1 border-border" />,
  table: ({ children }) => (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/60">{children}</thead>,
  th: ({ children, style }) => (
    <th style={style} className="border-b border-border px-3 py-1.5 text-left font-medium">
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td style={style} className="border-b border-border/60 px-3 py-1.5 align-top">
      {children}
    </td>
  ),
};

const plugins = [remarkGfm];

// What the lead wrote, which is Markdown, shown as a page would show it. What is in it that is HTML is shown as text,
// and never run.
export const Markdown = memo(function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3 break-words text-[15px] leading-7", className)}>
      <ReactMarkdown remarkPlugins={plugins} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
});
