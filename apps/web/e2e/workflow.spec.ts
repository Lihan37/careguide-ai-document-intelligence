import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd(), "../..");
const envText = fs
  .readFileSync(path.join(root, ".env"), "utf8")
  .replace(/^\uFEFF/, "");
const password = envText.match(/^DEMO_PASSWORD=(.+)$/m)?.[1].trim();

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
  const response = await page.request.get(`http://localhost:8000/api/documents/${id}`);
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
  const response = await page.request.get(`http://localhost:8000/api/documents/${documentId}`);
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
    path: path.join(root, "docs/dashboard-comparison.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Recent documents" }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(root, "docs/dashboard-preview.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(root, "docs/mobile-preview.png"),
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
