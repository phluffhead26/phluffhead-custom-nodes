import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
    ? require(join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'))
    : require('playwright');
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const host = spawn(process.env.PYTHON || 'python', ['tests/browser_host.py'], { cwd: root });
let browser;
try {
    const url = await new Promise((resolve, reject) => {
        let output = '';
        const timeout = setTimeout(() => reject(new Error('Test host startup timed out')), 10000);
        host.stderr.on('data', (data) => process.stderr.write(data));
        host.on('exit', (code) => { clearTimeout(timeout); reject(new Error(`Test host exited ${code}`)); });
        host.stdout.on('data', (data) => {
            output += data;
            if (output.includes('\n')) { clearTimeout(timeout); resolve(output.trim().split('\n')[0]); }
        });
    });
    browser = await chromium.launch({
        headless: true, args: ['--no-sandbox'],
        ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(() => window.ready && window.connected);
    const start = async () => {
        const response = await page.request.post(`${url}/test/start`);
        assert.equal(response.status(), 200);
        await page.getByRole('button', { name: 'Pick 4', exact: true }).waitFor();
        await page.waitForFunction(() => [...document.querySelectorAll('.phluffhead-picker img')].every(img => img.naturalWidth > 0));
        assert.equal((await (await page.request.get(`${url}/test/result`)).json()).state, 'waiting');
    };
    const result = async (state) => {
        await page.waitForFunction(async (state) => (await (await fetch('/test/result')).json()).state === state, state);
        return (await page.request.get(`${url}/test/result`)).json();
    };

    await start();
    assert.equal(await page.locator('.phluffhead-picker img').count(), 4);
    await page.getByRole('button', { name: 'Pick 4', exact: true }).click();
    let out = await result('selected');
    assert.deepEqual(out.shape, [1, 12, 16, 3]);
    assert.equal(out.value, 1);
    await page.getByText('Image 4 selected. Workflow continued.').waitFor();
    console.log('PASS: pause, real PNG previews, Pick 4, original output');

    await start();
    await page.evaluate(() => {
        const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'Pick 1');
        button.click(); button.click();
    });
    out = await result('selected');
    assert.equal(out.value, 0);
    assert.equal(await page.evaluate(() => window.submitCount), 2);
    console.log('PASS: same-input repeat, Pick 1, duplicate-click suppression');

    await start();
    await page.getByRole('button', { name: 'Stop', exact: true }).click();
    await result('stopped');
    await page.getByText('Selection cancelled. Queue again when ready.').waitFor();
    console.log('PASS: live Stop');

    await start();
    await page.request.post(`${url}/test/cancel`);
    await result('stopped');
    await page.getByText('Selection cancelled. Queue again when ready.').waitFor();
    console.log('PASS: native interrupt while paused');

    await start();
    await page.reload();
    await page.waitForFunction(() => window.ready && window.connected);
    await page.getByRole('button', { name: 'Pick 2', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Pick 2', exact: true }).click();
    out = await result('selected');
    assert.ok(Math.abs(out.value - 1 / 3) < 1e-6);
    console.log('PASS: page refresh recovers a pending selection');

    await start();
    await page.evaluate(() => window.api.dispatchEvent(new CustomEvent('phluffhead.pick.closed', {
        detail: { request_id: 'stale-token', outcome: 'cancelled' },
    })));
    assert.equal(await page.getByRole('button', { name: 'Pick 1', exact: true }).count(), 1);
    await page.evaluate(() => window.node.onRemoved());
    await result('stopped');
    console.log('PASS: stale close ignored, removing paused node cancels');
    assert.deepEqual(errors, []);
} finally {
    await browser?.close();
    host.kill('SIGTERM');
}
