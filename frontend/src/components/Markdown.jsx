import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Renders LLM output (headings, lists, tables, code) safely - no raw HTML.
export default function Markdown({ text }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
