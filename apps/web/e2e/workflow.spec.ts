import { test, expect } from "@playwright/test";
import path from "node:path";
import { readFileSync } from "node:fs";

const root = path.resolve(process.cwd(), "../..");
const context = require('./context.cjs');
const password = context.env.DEMO_PASSWORD;
const apiUrl = context.api_url;

test.beforeEach(async ({ request }) => {
  const response = await request.get(apiUrl + '/api/environment');
  expect(response.ok()).toBeTruthy();
  const identity = await response.json();
  expect(identity).toEqual({ environment: 'test', automation_kind: 'playwright', run_id: context.run_id });
});

test("document deletion confirms dependencies and preserves unrelated uploads", { tag: "@document-deletion" }, async ({ page }) => {
  const targetName = "temporary-deletion-invoice.pdf";
  const retainedName = "retained-deletion-check.xlsx";
  const temporary = { name: targetName, mimeType: "application/pdf", buffer: readFileSync(path.join(root, "sample-data/layout-invoice.pdf")) };
  const retained = { name: retainedName, mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: readFileSync(path.join(root, "sample-data/accounting.xlsx")) };
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Upload Documents", exact: true }).click();
  await page.getByLabel("Choose documents").setInputFiles([temporary, retained]);
  await page.getByRole("button", { name: "Upload 2 documents", exact: true }).click();
  await expect(page.getByRole("link", { name: "Open document", exact: true })).toHaveCount(2);

  const docs = await (await page.request.get(`${apiUrl}/api/documents`)).json();
  const targetId = docs.items.find((row: { filename: string }) => row.filename === targetName).id;
  const retainedId = docs.items.find((row: { filename: string }) => row.filename === retainedName).id;
  const targetUrl = `${apiUrl}/api/documents/${targetId}`;
  const retainedUrl = `${apiUrl}/api/documents/${retainedId}`;
  for (const endpoint of [targetUrl, retainedUrl]) {
    await expect.poll(async () => (await (await page.request.get(`${endpoint}/status`)).json()).status,
      { timeout: 30000 }).toMatch(/^(COMPLETED|REQUIRES_REVIEW)$/);
  }
  const comparison = await page.request.post(`${apiUrl}/api/comparisons`, { data: { document_ids: [targetId, retainedId] } });
  expect(comparison.status()).toBe(201);
  const comparisonUrl = `${apiUrl}/api/comparisons/${(await comparison.json()).id}`;
  const retainedBefore = await (await page.request.get(retainedUrl)).json();

  await page.getByRole("navigation").getByRole("link", { name: "Documents", exact: true }).click();
  const row = page.getByRole("row").filter({ hasText: targetName });
  await row.getByLabel(`Actions for ${targetName}`).click();
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete document?" });
  await expect(dialog.getByText(targetName, { exact: true })).toBeVisible();
  await expect(dialog.getByText(/Deletion is permanent/)).toBeVisible();
  await expect(dialog.locator("dl")).toContainText(/Dependent saved comparisons\s*1/);
  await expect(dialog.getByText("Inactive", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect((await page.request.get(comparisonUrl)).status()).toBe(200);
  await expect(row).toBeVisible();

  await row.getByRole("link", { name: new RegExp(targetName) }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await dialog.getByRole("button", { name: "Delete document and comparisons", exact: true }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole("status")).toContainText("Document and 1 saved comparison deleted.");
  await expect(row).toHaveCount(0);
  await expect(page.getByRole("row").filter({ hasText: retainedName })).toBeVisible();
  expect((await page.request.get(targetUrl)).status()).toBe(404);
  expect((await page.request.get(comparisonUrl)).status()).toBe(404);
  expect(await (await page.request.get(retainedUrl)).json()).toEqual(retainedBefore);

  await page.getByRole("navigation").getByRole("link", { name: "Upload Documents", exact: true }).click();
  await page.getByLabel("Choose documents").setInputFiles(temporary);
  await page.getByRole("button", { name: "Upload 1 document", exact: true }).click();
  const reuploaded = page.getByRole("link", { name: "Open document", exact: true });
  await expect(reuploaded).toBeVisible();
  const replacement = await reuploaded.getAttribute("href");
  expect(replacement).not.toBe(`/documents/${targetId}`);
  await expect.poll(async () => (await (await page.request.get(`${apiUrl}/api${replacement}/status`)).json()).status,
    { timeout: 30000 }).toMatch(/^(COMPLETED|REQUIRES_REVIEW)$/);
  await page.getByRole("navigation").getByRole("link", { name: "Documents", exact: true }).click();
  await row.getByLabel(`Actions for ${targetName}`).click();
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await dialog.getByRole("button", { name: "Delete document", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Document deleted.");
  await expect(row).toHaveCount(0);
  expect((await page.request.get(retainedUrl)).ok()).toBeTruthy();
});

test("equivalent retry preserves the current extraction in the browser", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Upload Documents", exact: true }).click();
  await page.getByLabel("Choose documents").setInputFiles(path.join(root, "sample-data/layout-invoice.pdf"));
  await page.getByRole("button", { name: "Upload 1 document", exact: true }).click();
  await page.getByRole("link", { name: "Open document", exact: true }).click();
  await expect(page.getByText("9350.00", { exact: true })).toBeVisible({ timeout: 45000 });
  const id = new URL(page.url()).pathname.split("/").pop();
  const extractionUrl = apiUrl + "/api/documents/" + id + "/extraction";
  const before = await (await page.request.get(extractionUrl)).json();
  await page.getByRole("button", { name: "Retry processing" }).click();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByText(/Equivalent extraction; current result retained/)).toBeVisible({ timeout: 45000 });
  const after = await (await page.request.get(extractionUrl)).json();
  expect(after).toEqual(before);
  await expect(page.getByRole("button", { name: "Compare retry candidate" })).toHaveCount(0);
});

test('scanned invoice reaches the dashboard with OCR evidence', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Password', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Sign in to workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  const settings = await page.request.get(apiUrl + '/api/settings');
  expect(settings.ok()).toBeTruthy();
  test.skip(!(await settings.json()).ocr_available, 'Configure Tesseract and its language data for the browser runner');
  await page.getByRole('link', { name: 'Upload Documents', exact: true }).click();
  await page.getByLabel('Choose documents').setInputFiles(path.join(root, 'sample-data/ocr/multipage.pdf'));
  await page.getByRole('button', { name: 'Upload 1 document', exact: true }).click();
  await page.getByRole('link', { name: 'Open document', exact: true }).click();
  await expect(page.getByText('176.00', { exact: true })).toBeVisible({ timeout: 45000 });
  await page.getByRole('tab', { name: 'Source text' }).click();
  await expect(page.getByRole('heading', { name: 'Page 2 · tesseract_ocr' })).toBeVisible();
  await expect(page.getByText(/mean word confidence/)).toHaveCount(2);
  const id = new URL(page.url()).pathname.split('/').pop();
  const response = await page.request.get(`${apiUrl}/api/documents/${id}/validation`);
  expect(await response.json()).toEqual({ outcome: 'PASSED', issues: [] });
});

test('compound VAT label preserves printed tax and all four invoice items', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Password', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Sign in to workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Upload Documents', exact: true }).click();
  await page.getByLabel('Choose documents').setInputFiles(path.join(root, 'sample-data/tax-layout-invoice.pdf'));
  await page.getByRole('button', { name: 'Upload 1 document', exact: true }).click();
  await page.getByRole('link', { name: 'Open document', exact: true }).click();
  await expect(page.getByText('Eastern Digital Solutions Ltd.', { exact: true })).toBeVisible({ timeout: 45000 });
  await expect(page.getByText('965.00', { exact: true })).toBeVisible();
  const id = new URL(page.url()).pathname.split('/').pop();
  const response = await page.request.get(`${apiUrl}/api/documents/${id}`);
  expect(response.ok()).toBeTruthy();
  const record = await response.json();
  expect(record.raw.invoice_number).toBe('EDS-INV-2026-042');
  expect(record.raw.subtotal).toBe('9650.00');
  expect(record.raw.tax).toBe('965.00');
  expect(record.raw.total).toBe('10615.00');
  expect(record.raw.currency).toBe('BDT');
  expect(record.raw.line_items).toHaveLength(4);
  expect(record.evidence.tax.excerpt).toContain('Tax (VAT 10%)');
  expect(record.issues.filter((issue: { severity: string }) => ['FAILED', 'REQUIRES_REVIEW'].includes(issue.severity))).toEqual([]);
  await page.getByRole('tab', { name: /^Validation/ }).click();
  await expect(page.getByText('Required Tax', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Invalid Tax', { exact: true })).toHaveCount(0);
});

test('positioned invoice extracts names, currency, totals and four table rows', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Password', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Sign in to workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Upload Documents', exact: true }).click();
  await page.getByLabel('Choose documents').setInputFiles(path.join(root, 'sample-data/layout-invoice.pdf'));
  await page.getByRole('button', { name: 'Upload 1 document', exact: true }).click();
  await page.getByRole('link', { name: 'Open document', exact: true }).click();
  await expect(page.getByText('Northstar Office Supplies Ltd.', { exact: true })).toBeVisible({ timeout: 45000 });
  await expect(page.getByText('CareGuide Demo Operations', { exact: true })).toBeVisible();
  await expect(page.getByText('9350.00', { exact: true })).toBeVisible();
  const documentId = new URL(page.url()).pathname.split('/').pop();
  const response = await page.request.get(`${apiUrl}/api/documents/${documentId}`);
  expect(response.ok()).toBeTruthy();
  const record = await response.json();
  expect(record.raw.invoice_number).toBe('CG-2026-001');
  expect(record.raw.subtotal).toBe('8500.00');
  expect(record.raw.tax).toBe('850.00');
  expect(record.raw.currency).toBe('BDT');
  expect(record.raw.line_items).toHaveLength(4);
  expect(record.evidence.line_items.items[0].quantity.bbox).toHaveLength(4);
  expect(record.issues.filter((issue: { severity: string }) => ['FAILED', 'REQUIRES_REVIEW'].includes(issue.severity))).toEqual([]);
});

test("real invoice upload, processing, validation, correction, search and comparison", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Upload Documents", exact: true })
    .click();
  await page
    .getByLabel("Choose documents")
    .setInputFiles(path.join(root, "sample-data/incorrect-total.pdf"));
  await page
    .getByRole("button", { name: "Upload 1 document", exact: true })
    .click();
  await page.getByRole("link", { name: "Open document", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Structured extraction", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("250.00", { exact: true }).first()).toBeVisible({
    timeout: 45000,
  });
  await page.getByRole("tab", { name: /^Validation/ }).click();
  await expect(
    page.getByText("Arithmetic differs beyond currency tolerance", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Corrections", exact: true }).click();
  await page.getByLabel("Correct Total", { exact: true }).fill("220.00");
  await page
    .getByLabel("Reason for correction")
    .fill("Browser test: reconcile source subtotal and tax");
  await page
    .getByRole("button", { name: "Save correction", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Correction saved");
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(page.getByText(/^Correction ·/)).toBeVisible();
  await page.getByRole("tab", { name: /^Validation/ }).click();
  await page
    .getByLabel("Review note")
    .fill("Browser test: confirmed arithmetic and original extraction");
  await page.getByRole("button", { name: "Approve result" }).click();
  await expect(page.getByRole("status")).toContainText("Review approved");
  await page.getByRole("link", { name: "Search", exact: true }).click();
  await page.getByLabel("Search documents").fill("CG-2026-002");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(
    page.getByRole("link", { name: /incorrect-total.pdf/ }).first(),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Upload Documents", exact: true })
    .click();
  await page
    .getByLabel("Choose documents")
    .setInputFiles(path.join(root, "sample-data/accounting.xlsx"));
  await page
    .getByRole("button", { name: "Upload 1 document", exact: true })
    .click();
  await page.getByRole("link", { name: "Open document", exact: true }).click();
  await expect(page.getByText("225.00", { exact: true }).first()).toBeVisible({
    timeout: 45000,
  });
  await page
    .getByRole("link", { name: "Document Comparison", exact: true })
    .click();
  await page
    .locator("label.selection-card")
    .filter({ hasText: "incorrect-total.pdf" })
    .first()
    .getByRole("checkbox")
    .check();
  await page
    .locator("label.selection-card")
    .filter({ hasText: "accounting.xlsx" })
    .first()
    .getByRole("checkbox")
    .check();
  await page
    .getByRole("button", { name: "Compare 2 documents", exact: true })
    .click();
  await expect(
    page.getByText("Mismatched", { exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(context.root, "artifacts/dashboard-comparison.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Recent documents" }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(context.root, "artifacts/dashboard-preview.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(context.root, "artifacts/mobile-preview.png"),
    fullPage: true,
  });
});

test("valid invoice, duplicate warning, corrupt file retry and connected navigation", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  const uploadAndOpen = async (filename: string) => {
    await page
      .getByRole("link", { name: "Upload Documents", exact: true })
      .click();
    await page
      .getByLabel("Choose documents")
      .setInputFiles(path.join(root, "sample-data", filename));
    await page
      .getByRole("button", { name: "Upload 1 document", exact: true })
      .click();
    await page
      .getByRole("link", { name: "Open document", exact: true })
      .click();
  };
  await uploadAndOpen("invoice.pdf");
  await expect(page.getByText("220.00", { exact: true }).first()).toBeVisible({
    timeout: 45000,
  });
  await page.getByRole("tab", { name: /^Validation/ }).click();
  await expect(
    page.getByText("Arithmetic differs beyond currency tolerance", {
      exact: true,
    }),
  ).toHaveCount(0);
  await uploadAndOpen("duplicate.pdf");
  await page.getByRole("tab", { name: /^Validation/ }).click();
  await expect(
    page.getByText("Exact file checksum match", { exact: true }).first(),
  ).toBeVisible({ timeout: 45000 });
  await uploadAndOpen("corrupted.pdf");
  await expect(page.locator(".detail-summary .badge")).toHaveText("Failed", {
    timeout: 45000,
  });
  await page
    .getByRole("button", { name: "Retry processing", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Reprocessing requested",
  );
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(page.getByText(/retry 1/).first()).toBeVisible({
    timeout: 45000,
  });
  await expect(page.locator(".detail-summary .badge")).toHaveText("Failed", {
    timeout: 45000,
  });
  for (const name of [
    "Documents",
    "Processing Jobs",
    "Review Queue",
    "Evaluation",
    "Settings",
  ]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole("button", { name: "Check services", exact: true })
    .click();
  await expect(page.getByText(/ready\. Inspect processing jobs/)).toBeVisible();
});
