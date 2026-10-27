const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { resolve } = require('node:path');

function setup(fetch) {
    const context = vm.createContext({ fetch, state: { token: 'old' }, localStorage: { setItem() {} }, utils: { showAlert() {} }, logout: async () => { context.logouts++; context.state.token = null; }, logouts: 0 });
    vm.runInContext(readFileSync(resolve(__dirname, '../static/apis.js'), 'utf8') + '\nglobalThis.apis = apis;', context);
    return context;
}

test('refresh succeeds but repeated 401 stops after one retry', async () => {
    let refreshes = 0;
    const ctx = setup(async url => url.endsWith('/refresh') ? (++refreshes, { ok: true, json: async () => ({ access_token: 'new' }) }) : { status: 401 });
    await assert.rejects(ctx.apis.request('/users/me', {}, true), /다시 로그인/);
    assert.equal(refreshes, 1);
    assert.equal(ctx.logouts, 1);
});

test('concurrent requests share failed refresh and both terminate', async () => {
    let refreshes = 0;
    const ctx = setup(async url => {
        if (url.endsWith('/refresh')) {
            refreshes++;
            await new Promise(resolve => setTimeout(resolve, 10));
            return { ok: false };
        }
        return { status: 401 };
    });
    const result = await Promise.allSettled([ctx.apis.request('/users/me', {}, true), ctx.apis.request('/users/me', {}, true)]);
    assert.equal(refreshes, 1);
    assert.ok(result.every(item => item.status === 'rejected'));
});

test('password visibility toggles only the selected input', () => {
    const input = { type: 'password' };
    const button = { setAttribute(name, value) { this[name] = value; } };
    const ctx = vm.createContext({ document: { getElementById: () => input } });
    vm.runInContext(readFileSync(resolve(__dirname, '../static/utils.js'), 'utf8') + '\nglobalThis.utils = utils;', ctx);
    ctx.utils.togglePassword('password', button);
    assert.equal(input.type, 'text');
    assert.equal(button['aria-pressed'], 'true');
    ctx.utils.togglePassword('password', button);
    assert.equal(input.type, 'password');
});
