/**
 * Минимальный markdown-renderer для статичных доков (FEATURES.md и пр.).
 * Поддерживает: # ## ### #### заголовки, **bold**, *italic*, `code`,
 * [text](url), таблицы | a | b |, ordered/unordered списки, --- hr,
 * блок-цитаты >, code-блоки ```.
 *
 * Не подключаем react-markdown / remark-gfm чтобы не раздувать bundle —
 * субсет нашего markdown достаточно простой.
 */
import { Link } from "react-router-dom";

type Block =
  | { type: "h"; level: number; text: string; id: string }
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][]; aligns: ("l" | "c" | "r")[] }
  | { type: "code"; lang: string; text: string }
  | { type: "quote"; text: string }
  | { type: "hr" }
  | { type: "raw"; html: string };

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-zа-яё0-9\s-]/gi, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 80);
}

function parse(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block ```
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", lang, text: buf.join("\n") });
      continue;
    }

    // Horizontal rule
    if (/^---+\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Heading
    const hMatch = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (hMatch) {
      const level = hMatch[1].length;
      const text = hMatch[2];
      blocks.push({ type: "h", level, text, id: slugify(text) });
      i++;
      continue;
    }

    // Table
    if (line.includes("|") && i + 1 < lines.length && /^\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const headers = splitTableRow(line);
      const alignsRaw = splitTableRow(lines[i + 1]);
      const aligns: ("l" | "c" | "r")[] = alignsRaw.map((s) => {
        const t = s.trim();
        if (t.startsWith(":") && t.endsWith(":")) return "c";
        if (t.endsWith(":")) return "r";
        return "l";
      });
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim().length > 0) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows, aligns });
      continue;
    }

    // Blockquote
    if (line.startsWith("> ")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith("> ")) {
        buf.push(lines[i].slice(2));
        i++;
      }
      blocks.push({ type: "quote", text: buf.join(" ") });
      continue;
    }

    // Unordered list. Допускаем:
    //   - пустые строки между bullet'ами (не разбивать на 2 списка),
    //   - continuation-строки (отступ ≥ 2 пробела) — приклеиваем к текущему item.
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length) {
        const cur = lines[i];
        if (/^[-*]\s+/.test(cur)) {
          items.push(cur.replace(/^[-*]\s+/, ""));
          i++;
        } else if (cur.trim() === "" && i + 1 < lines.length &&
                   /^[-*]\s+/.test(lines[i + 1])) {
          // Пустая строка внутри списка — пропустить, не закрывая <ul>.
          i++;
        } else if (/^\s{2,}\S/.test(cur) && items.length > 0) {
          // Continuation: текст с отступом, приклеить к последнему item.
          items[items.length - 1] += " " + cur.trim();
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Ordered list — те же правила что и для ul.
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length) {
        const cur = lines[i];
        if (/^\d+\.\s+/.test(cur)) {
          items.push(cur.replace(/^\d+\.\s+/, ""));
          i++;
        } else if (cur.trim() === "" && i + 1 < lines.length &&
                   /^\d+\.\s+/.test(lines[i + 1])) {
          i++;
        } else if (/^\s{2,}\S/.test(cur) && items.length > 0) {
          items[items.length - 1] += " " + cur.trim();
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Empty line — skip
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: collect lines до пустой/блочной
    const buf: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].startsWith("#") &&
      !lines[i].startsWith("```") &&
      !/^---+\s*$/.test(lines[i]) &&
      !/^[-*]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i]) &&
      !lines[i].startsWith("> ")
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ type: "p", text: buf.join(" ") });
  }

  return blocks;
}

function splitTableRow(line: string): string[] {
  // | a | b | c | → ["a", "b", "c"]
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((s) => s.trim());
}

/**
 * Inline-форматирование: **bold**, *italic*, `code`, [text](url).
 * Возвращает React-фрагменты.
 */
function renderInline(text: string, keyPrefix = ""): React.ReactNode[] {
  // Сначала разрезаем по link-pattern, потом форматируем оставшиеся части.
  const out: React.ReactNode[] = [];
  const linkRe = /\[([^\]]+)\]\(([^)]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = linkRe.exec(text)) !== null) {
    if (m.index > last) {
      out.push(...renderInlineNoLinks(text.slice(last, m.index), `${keyPrefix}t${k++}`));
    }
    const label = m[1];
    const url = m[2];
    const key = `${keyPrefix}l${k++}`;
    if (url.startsWith("#")) {
      // Anchor link внутри страницы
      out.push(
        <a key={key} href={url} className="text-accent hover:underline">
          {label}
        </a>,
      );
    } else if (url.endsWith(".md") || url.startsWith("/")) {
      // Внутренние .md или route — открываем как Link если route, иначе ничего не делаем
      if (url.startsWith("/")) {
        out.push(
          <Link key={key} to={url} className="text-accent hover:underline">
            {label}
          </Link>,
        );
      } else {
        out.push(
          <span key={key} className="text-accent">
            {label}
          </span>,
        );
      }
    } else {
      out.push(
        <a key={key} href={url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
          {label}
        </a>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    out.push(...renderInlineNoLinks(text.slice(last), `${keyPrefix}t${k++}`));
  }
  return out;
}

// In-app routes: backtick-код, матчящийся `^/[a-z][a-z0-9-/?#=&_]*$`,
// рендерится как кликабельный <Link>. Это даёт quick-navigation в
// `/features` (USER_GUIDE.md и FEATURES.md). External URLs (http://, https://)
// обрабатываются отдельно — они используют [text](url) markdown синтаксис.
function isInAppPath(s: string): boolean {
  return /^\/[a-z][a-z0-9\-/?#=&_]*$/.test(s);
}

function renderInlineNoLinks(text: string, keyPrefix = ""): React.ReactNode[] {
  // Inline code (backticks) — highest priority, split first
  const out: React.ReactNode[] = [];
  const codeRe = /`([^`]+)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = codeRe.exec(text)) !== null) {
    if (m.index > last) {
      out.push(...renderBoldItalic(text.slice(last, m.index), `${keyPrefix}c${k++}`));
    }
    const codeText = m[1];
    if (isInAppPath(codeText)) {
      // Кликабельный путь — Link с тем же visual styling (mono + accent).
      out.push(
        <Link
          key={`${keyPrefix}link${k++}`}
          to={codeText}
          className="bg-surface-2 text-accent hover:text-accent-strong hover:underline px-1 py-0.5 rounded text-[0.85em] font-mono"
        >
          {codeText}
        </Link>,
      );
    } else {
      out.push(
        <code key={`${keyPrefix}code${k++}`} className="bg-surface-2 text-accent px-1 py-0.5 rounded text-[0.85em] font-mono">
          {codeText}
        </code>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    out.push(...renderBoldItalic(text.slice(last), `${keyPrefix}c${k++}`));
  }
  return out;
}

function renderBoldItalic(text: string, keyPrefix = ""): React.ReactNode[] {
  // **bold** then *italic*
  const out: React.ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      out.push(<span key={`${keyPrefix}s${k++}`}>{text.slice(last, m.index)}</span>);
    }
    if (m[1] !== undefined) {
      out.push(
        <strong key={`${keyPrefix}b${k++}`} className="font-semibold">
          {m[1]}
        </strong>,
      );
    } else if (m[2] !== undefined) {
      out.push(
        <em key={`${keyPrefix}i${k++}`} className="italic">
          {m[2]}
        </em>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    out.push(<span key={`${keyPrefix}s${k++}`}>{text.slice(last)}</span>);
  }
  return out;
}

export default function MarkdownLite({ source }: { source: string }) {
  const blocks = parse(source);
  return (
    <div className="space-y-2 leading-snug text-sm">
      {blocks.map((b, idx) => {
        switch (b.type) {
          case "h": {
            const sizeCls =
              b.level === 1
                ? "text-2xl font-bold mt-5 mb-2 pb-2 border-b border-border"
                : b.level === 2
                  ? "text-xl font-semibold mt-5 mb-1.5"
                  : b.level === 3
                    ? "text-lg font-semibold mt-3 mb-1"
                    : "text-base font-semibold mt-2 mb-0.5";
            const Tag = `h${b.level}` as keyof JSX.IntrinsicElements;
            return (
              <Tag key={idx} id={b.id} className={sizeCls}>
                {renderInline(b.text, `h${idx}`)}
              </Tag>
            );
          }
          case "p":
            return (
              <p key={idx} className="text-fg leading-snug">
                {renderInline(b.text, `p${idx}`)}
              </p>
            );
          case "ul":
            return (
              <ul key={idx} className="list-disc pl-5 space-y-0.5">
                {b.items.map((it, j) => (
                  <li key={j} className="leading-snug">
                    {renderInline(it, `ul${idx}_${j}`)}
                  </li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={idx} className="list-decimal pl-5 space-y-0.5">
                {b.items.map((it, j) => (
                  <li key={j} className="leading-snug">
                    {renderInline(it, `ol${idx}_${j}`)}
                  </li>
                ))}
              </ol>
            );
          case "table":
            return (
              <div key={idx} className="overflow-x-auto -mx-4 sm:mx-0">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-border">
                      {b.headers.map((h, j) => (
                        <th
                          key={j}
                          className={`px-3 py-2 font-semibold text-tiny uppercase tracking-wider text-muted text-${b.aligns[j] === "c" ? "center" : b.aligns[j] === "r" ? "right" : "left"}`}
                        >
                          {renderInline(h, `th${idx}_${j}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, ri) => (
                      <tr key={ri} className="border-b border-border/40 hover:bg-surface-2/40">
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            className={`px-3 py-2 align-top text-${b.aligns[ci] === "c" ? "center" : b.aligns[ci] === "r" ? "right" : "left"}`}
                          >
                            {renderInline(cell, `td${idx}_${ri}_${ci}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "code":
            return (
              <pre key={idx} className="bg-surface-2 border border-border rounded p-3 overflow-x-auto text-xs font-mono">
                <code>{b.text}</code>
              </pre>
            );
          case "quote":
            return (
              <blockquote key={idx} className="border-l-4 border-accent pl-3 py-1 text-muted bg-surface-2/30">
                {renderInline(b.text, `q${idx}`)}
              </blockquote>
            );
          case "hr":
            return <hr key={idx} className="border-border my-6" />;
          case "raw":
            return <div key={idx} dangerouslySetInnerHTML={{ __html: b.html }} />;
        }
      })}
    </div>
  );
}
