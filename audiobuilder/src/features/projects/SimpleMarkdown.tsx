import React from "react";

// ---------------------------------------------------------------------------
// Simple markdown renderer (no external deps)
// ---------------------------------------------------------------------------

export function SimpleMarkdown({ content }: { content: string }) {
  // Very lightweight markdown → HTML conversion for preview
  const html = React.useMemo(() => {
    const out = content
      // Escape HTML
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      // Headings
      .replace(/^### (.+)$/gm, "<h3>$1</h3>")
      .replace(/^## (.+)$/gm, "<h2>$1</h2>")
      .replace(/^# (.+)$/gm, "<h1>$1</h1>")
      // Bold / italic
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      // Inline code
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      // Unordered list items
      .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
      // Ordered list items
      .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
      // Horizontal rule
      .replace(/^---$/gm, "<hr/>")
      // Paragraphs (double newline)
      .replace(/\n\n/g, "</p><p>")
      // Single newlines
      .replace(/\n/g, "<br/>");
    return `<p>${out}</p>`;
  }, [content]);

  return (
    <div
      className="prose prose-sm max-w-none dark:prose-invert text-secondary-800 dark:text-secondary-200 [&_h1]:text-xl [&_h1]:font-bold [&_h2]:text-lg [&_h2]:font-bold [&_h3]:text-base [&_h3]:font-semibold [&_code]:rounded [&_code]:bg-secondary-100 [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_code]:dark:bg-secondary-700 [&_hr]:border-secondary-300 [&_li]:ml-4 [&_li]:list-disc"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
