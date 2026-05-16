/**
 * Снимок DOM-узла → PDF / PNG. Используется для «export Dashboard».
 *
 * - PDF: одна страница A4 landscape, контент масштабируется чтобы влез по ширине
 * - PNG: один большой png-файл прямой выгрузки
 *
 * Ограничения html2canvas:
 * - Внешние изображения (с другого origin) могут не отрендериться без CORS.
 *   У нас все изображения через `/api/products/{nm}/photo` proxy, same-origin.
 * - SVG из recharts рисуются корректно — recharts использует <foreignObject>.
 * - sticky-positions могут сбиться — но в Dashboard их нет.
 */
import html2canvas from "html2canvas";
import jsPDF from "jspdf";

const PDF_MARGIN_MM = 10;

async function snapshot(node: HTMLElement): Promise<HTMLCanvasElement> {
  // Скрываем скроллбар, белая подложка
  return html2canvas(node, {
    backgroundColor: "#0a0a0a", // совпадает с tailwind bg-bg (тёмная тема)
    scale: 2, // ретина-качество
    useCORS: true,
    logging: false,
    windowWidth: node.scrollWidth,
    windowHeight: node.scrollHeight,
  });
}

function nowFilename(prefix: string, ext: string): string {
  const d = new Date();
  const ts = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}-${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}`;
  return `${prefix}-${ts}.${ext}`;
}

export async function exportToPng(
  node: HTMLElement,
  filenamePrefix: string = "dashboard",
): Promise<void> {
  const canvas = await snapshot(node);
  const link = document.createElement("a");
  link.download = nowFilename(filenamePrefix, "png");
  link.href = canvas.toDataURL("image/png");
  link.click();
}

export async function exportToPdf(
  node: HTMLElement,
  filenamePrefix: string = "dashboard",
  title: string = "Дашборд",
): Promise<void> {
  const canvas = await snapshot(node);
  // A4 landscape: 297 x 210 mm
  const pdf = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const usableW = pageWidth - PDF_MARGIN_MM * 2;
  const usableH = pageHeight - PDF_MARGIN_MM * 2 - 12; // 12mm для заголовка

  // Aspect-fit изображения по ширине
  const imgRatio = canvas.height / canvas.width;
  let renderW = usableW;
  let renderH = renderW * imgRatio;

  // Если высота больше доступной — разбиваем на несколько страниц
  const pagesCount = Math.ceil(renderH / usableH);
  const pageContentHeight = renderH / pagesCount;
  // Пиксельная высота одного куска оригинального canvas
  const sliceHeightPx = canvas.height / pagesCount;

  for (let i = 0; i < pagesCount; i++) {
    if (i > 0) pdf.addPage();
    // Заголовок
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(11);
    pdf.text(
      `${title} · стр ${i + 1}/${pagesCount} · ${new Date().toLocaleString("ru-RU")}`,
      PDF_MARGIN_MM,
      PDF_MARGIN_MM,
    );
    // Вырезаем кусок canvas-а
    const sliceCanvas = document.createElement("canvas");
    sliceCanvas.width = canvas.width;
    sliceCanvas.height = sliceHeightPx;
    const ctx = sliceCanvas.getContext("2d");
    if (!ctx) continue;
    ctx.drawImage(
      canvas,
      0,
      i * sliceHeightPx,
      canvas.width,
      sliceHeightPx,
      0,
      0,
      canvas.width,
      sliceHeightPx,
    );
    pdf.addImage(
      sliceCanvas.toDataURL("image/png"),
      "PNG",
      PDF_MARGIN_MM,
      PDF_MARGIN_MM + 6,
      renderW,
      pageContentHeight,
    );
  }

  pdf.save(nowFilename(filenamePrefix, "pdf"));
}
