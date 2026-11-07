// Minimal PDF with Helvetica text lines (48 per page), for document preparation checks.
export function pdfFixture(lines, { padBytes = 0 } = {}) {
  const pages = [];
  for (let start = 0; start < Math.max(lines.length, 1); start += 48) pages.push(lines.slice(start, start + 48));
  const font = 3 + pages.length * 2;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [' + pages.map((_, index) => (3 + index * 2) + ' 0 R').join(' ') + '] /Count ' + pages.length + ' >>',
  ];
  for (const [index, page] of pages.entries()) {
    const stream = page.length
      ? 'BT /F1 12 Tf 72 720 Td 14 TL ' + page.map((line) => '(' + line.replace(/[\\()]/g, '\\$&') + ') Tj T*').join(' ') + ' ET'
      : '';
    objects.push(
      '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ' + font + ' 0 R >> >> /Contents ' + (4 + index * 2) + ' 0 R >>',
      '<< /Length ' + stream.length + ' >>\nstream\n' + stream + '\nendstream',
    );
  }
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  if (padBytes) objects.push('<< /Length ' + padBytes + ' >>\nstream\n' + ' '.repeat(padBytes) + '\nendstream');
  let body = '%PDF-1.4\n';
  const offsets = objects.map((object, index) => {
    const offset = body.length;
    body += (index + 1) + ' 0 obj\n' + object + '\nendobj\n';
    return offset;
  });
  const xref = body.length;
  body += 'xref\n0 ' + (objects.length + 1) + '\n0000000000 65535 f \n' +
    offsets.map((offset) => String(offset).padStart(10, '0') + ' 00000 n \n').join('') +
    'trailer\n<< /Size ' + (objects.length + 1) + ' /Root 1 0 R >>\nstartxref\n' + xref + '\n%%EOF\n';
  return Buffer.from(body, 'latin1');
}
