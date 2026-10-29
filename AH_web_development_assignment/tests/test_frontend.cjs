// Run: node --test tests/test_frontend.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
    const elements = new Map();
    const get = id => {
        if (!elements.has(id)) elements.set(id, {
            innerHTML: '', value: '', addEventListener() {},
            classList: { add() {}, remove() {} }
        });
        return elements.get(id);
    };
    const context = vm.createContext({
        document: { getElementById: get, addEventListener() {}, body: { classList: { add() {}, remove() {} } } },
        localStorage: { getItem() { return null; } },
        window: { location: { origin: 'http://localhost:8000' }, history: { pushState() {} } },
        URL, console, apis: {}
    });
    for (const name of ['utils', 'pages', 'app']) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, '../static', `${name}.js`), 'utf8'), context);
    }
    vm.runInContext('globalThis.testApp = { utils, pages, state, navigate, updateNav };', context);
    const app = context.testApp;
    app.utils.loadTemplate = async () => 'template';
    app.state.user = { id: 1, role: 'admin' };
    return { ...app, apis: context.apis, get };
}
const payload = '<img src=x onerror=alert(1)>';
const patient = id => ({ id, name: payload, age: 30, gender: 'male', phone_number: '01012345678' });
const deferred = () => {
    let resolve;
    const promise = new Promise(r => { resolve = r; });
    return { promise, resolve };
};

test('patient, record, admin and navigation text is escaped', async () => {
    const a = setup();
    a.apis.getPatients = async () => [patient(1)];
    await a.navigate('/patients');
    assert.ok(a.get('patients-list').innerHTML.includes(a.utils.escapeHtml(payload)));
    assert.ok(!a.get('patients-list').innerHTML.includes(payload));
    a.apis.getPatient = async () => patient(1);
    a.apis.getPatientMedicalRecords = async () => [{ id: 1, chart_number: payload, symptoms: payload }];
    await a.navigate('/patients/1');
    assert.ok(!a.get('records-list').innerHTML.includes(payload));
    assert.ok(a.get('records-list').innerHTML.includes(a.utils.escapeHtml(payload)));
    a.apis.adminGetUsers = async () => [{ id: 2, name: payload, email: payload, department: payload }];
    await a.navigate('/admin/users');
    assert.ok(!a.get('admin-users-list').innerHTML.includes(payload));
    a.state.user.name = payload;
    a.updateNav();
    assert.ok(!a.get('auth-link').innerHTML.includes(payload));
    a.apis.getPatients = async () => { throw new Error(payload); };
    await a.navigate('/patients');
    assert.ok(!a.get('app').innerHTML.includes(payload));
    assert.ok(a.get('app').innerHTML.includes(a.utils.escapeHtml(payload)));
    assert.equal(a.utils.escapeHtml('&<>"\''), '&amp;&lt;&gt;&quot;&#39;');
});

test('late patient response cannot replace current patient or mutation target', async () => {
    const a = setup(), old = deferred();
    a.apis.getPatient = id => id === '1' ? old.promise : Promise.resolve(patient(2));
    a.apis.getPatientMedicalRecords = async () => [];
    const first = a.navigate('/patients/1');
    await a.navigate('/patients/2');
    old.resolve(patient(1));
    await first;
    assert.equal(a.state.currentPatientId, '2');
    let updated, deleted;
    a.apis.updatePatient = async id => { updated = id; };
    a.apis.deletePatient = async id => { deleted = id; };
    a.utils.showAlert = () => {};
    a.get('update-phone').value = '01012345678';
    await a.pages.handlePatientUpdate({ preventDefault() {} });
    await a.pages.handlePatientDelete();
    assert.equal(updated, '2');
    assert.equal(deleted, '2');
});

test('returning to same URL rejects the first visit response', async () => {
    const a = setup(), old = deferred();
    let calls = 0;
    a.apis.getPatient = () => ++calls === 1 ? old.promise : Promise.resolve({ ...patient(1), name: 'latest' });
    a.apis.getPatientMedicalRecords = async () => [];
    const first = a.navigate('/patients/1');
    await a.navigate('/');
    assert.equal(a.state.currentPatientId, null);
    await a.navigate('/patients/1');
    old.resolve({ ...patient(1), name: 'stale' });
    await first;
    assert.equal(a.get('patient-name').innerText, 'latest (남성)');
});

test('late errors do not replace a new patient screen', async () => {
    const a = setup(), old = deferred();
    a.apis.getPatient = async id => { if (id === '1') { await old.promise; throw new Error('old error'); } return patient(2); };
    a.apis.getPatientMedicalRecords = async () => [];
    const first = a.navigate('/patients/1');
    await a.navigate('/patients/2');
    old.resolve();
    await first;
    assert.equal(a.get('app').innerHTML, 'template');
    assert.equal(a.state.currentPatientId, '2');
});
