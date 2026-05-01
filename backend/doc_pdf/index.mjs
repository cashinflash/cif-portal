/**
 * cif-portal-doc-pdf — HTML → PDF conversion Lambda.
 *
 * Driven from the loans Lambda (Python) via boto3 lambda.invoke when
 * a customer requests `?format=pdf` on /api/my-loans/documents/{id}/
 * download. Uses headless Chromium via @sparticuz/chromium and
 * puppeteer-core to render Vergent's signed-document HTML to a real
 * PDF the browser can save with one click.
 *
 * Direct invocation only (no API Gateway). Event payload:
 *   { html: "<!doctype html>...", fileName: "Loan Agreement.pdf",
 *     title: "Loan Agreement" }
 *
 * Response shape:
 *   { ok: true, pdfBase64: "...", fileName: "...pdf" } on success
 *   { ok: false, error: "<reason>", detail: "..." }   on failure
 *
 * Memory: 1024 MB minimum (Chromium needs the headroom).
 * Timeout: 30 s (typical render is 2–5 s; cold start adds ~5 s).
 * Architecture: x86_64 (matches @sparticuz/chromium's binaries).
 */
import chromium from '@sparticuz/chromium';
import puppeteer from 'puppeteer-core';

// Re-deploy 2026-05-01: replaces placeholder code created by
// provision-doc-pdf.yml with the real handler now that the function
// exists in AWS. (This comment also serves as the path-filter trigger
// for deploy-doc-pdf.yml on backend/doc_pdf/**.)

// Reuse the browser across warm invocations — Chromium startup is the
// slowest part of a render, so amortising it pays off when the Lambda
// is hit twice in close succession.
let _browser = null;

async function getBrowser() {
  if (_browser && _browser.connected !== false) {
    try {
      // Sanity: if any active page is unresponsive, re-launch.
      await _browser.version();
      return _browser;
    } catch (_) {
      try { await _browser.close(); } catch (_) { /* ignore */ }
      _browser = null;
    }
  }
  _browser = await puppeteer.launch({
    args: chromium.args,
    defaultViewport: { width: 1100, height: 1500, deviceScaleFactor: 1 },
    executablePath: await chromium.executablePath(),
    headless: chromium.headless,
  });
  return _browser;
}

export const handler = async (event) => {
  const html = event && event.html;
  const fileName = (event && event.fileName) || 'document.pdf';
  if (!html || typeof html !== 'string') {
    return { ok: false, error: 'missing_html' };
  }

  let page = null;
  try {
    const browser = await getBrowser();
    page = await browser.newPage();

    // Vergent's docs reference external CSS at shared.vergentlms.com.
    // Wait for those, but cap aggressively so we don't stall a render
    // because an asset is slow.
    await page.setContent(html, {
      waitUntil: 'networkidle2',
      timeout: 12000,
    });

    const pdf = await page.pdf({
      format: 'Letter',
      printBackground: true,
      preferCSSPageSize: false,
      margin: {
        top: '0.5in',
        right: '0.5in',
        bottom: '0.5in',
        left: '0.5in',
      },
    });

    return {
      ok: true,
      pdfBase64: Buffer.from(pdf).toString('base64'),
      fileName: fileName.endsWith('.pdf') ? fileName : fileName + '.pdf',
    };
  } catch (err) {
    console.error('pdf-render failed', err && err.message);
    return {
      ok: false,
      error: 'render_failed',
      detail: (err && err.message) ? err.message.slice(0, 300) : '',
    };
  } finally {
    if (page) {
      try { await page.close(); } catch (_) { /* ignore */ }
    }
  }
};
