(function () {
  'use strict';

  function uiIcon(name) {
    const image = document.createElement('img'); image.className = 'ui-icon'; image.src = './assets/' + name + '.svg'; image.alt = ''; return image;
  }
  function flowIcon(flow) {
    if (flow.direction === 'income') return 'currency-circle-dollar';
    if (isCard(flow)) return 'credit-card';
    if (/household/i.test(flow.name)) return 'house';
    if (/feed/i.test(flow.name)) return 'shopping-cart';
    if (/internet/i.test(flow.name)) return 'wifi-high';
    if (/loan|repay/i.test(flow.name)) return 'gift';
    return 'receipt';
  }
  function displayName(flow) {
    const labels = {};
    const original = DEFAULT_STATE.flows.find(item => item.id === flow.id);
    return original && original.name === flow.name ? labels[flow.id] || flow.name : flow.name;
  }

  const STORAGE_KEY = 'money-map-v1';
  const DEFAULT_STATE = {
    version: 1,
    asOf: '2026-11-01',
    startingCash: 8000,
    scenario: 'average',
    horizon: 3,
    flows: [
      { id: 'pay-10', name: '10th payday', direction: 'income', schedule: 'monthly', amount: 18000, lowAmount: 16500, day: 10, start: '2026-11-01', end: '', category: 'Pay', confidence: 'estimate', note: 'Sample data.' },
      { id: 'pay-25', name: '25th payday', direction: 'income', schedule: 'monthly', amount: 18000, lowAmount: 16500, day: 25, start: '2026-11-01', end: '', category: 'Pay', confidence: 'estimate', note: 'Sample data.' },
      { id: 'rent', name: 'Rent', direction: 'expense', schedule: 'monthly', amount: 9000, day: 10, start: '2026-11-01', end: '', category: 'Household', confidence: 'confirmed', note: '' },
      { id: 'electric', name: 'Electricity', direction: 'expense', schedule: 'monthly', amount: 2500, day: 10, start: '2026-11-01', end: '', category: 'Utilities', confidence: 'estimate', note: '' },
      { id: 'internet', name: 'Internet', direction: 'expense', schedule: 'monthly', amount: 1500, day: 25, start: '2026-11-01', end: '', category: 'Utilities', confidence: 'confirmed', note: '' },
      { id: 'groceries', name: 'Groceries', direction: 'expense', schedule: 'monthly', amount: 4000, day: 25, start: '2026-11-01', end: '', category: 'Food', confidence: 'estimate', note: '' },
      { id: 'phone-plan', name: 'Phone plan', direction: 'expense', schedule: 'monthly', amount: 999, day: 25, start: '2026-11-01', end: '', category: 'Utilities', confidence: 'confirmed', note: '' },
      { id: 'card-pay', name: 'Credit card payment', direction: 'expense', schedule: 'monthly', amount: 3000, day: 10, start: '2026-11-01', end: '', category: 'Debt', kind: 'card', confidence: 'estimate', note: '' }
    ],
    balances: [
      { id: 'card-balance', name: 'Credit card', kind: 'debt', amount: 45000, asOf: '2026-11-01', note: 'Sample data.' }
    ]
  };

  const peso0 = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', maximumFractionDigits: 0 });
  const peso2 = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const shortDate = new Intl.DateTimeFormat('en-PH', { month: 'short', day: 'numeric', year: 'numeric' });
  const monthName = new Intl.DateTimeFormat('en-PH', { month: 'short', year: 'numeric' });
  let state = loadState();
  let lastForecast = null;
  let toastTimer = null;
  let selectedOccurrence = null;
  let upcomingFilter = 'all';
  let budgetGroups = [];
  let scopeMonth = monthKey(dateFrom(today() > state.asOf ? today() : state.asOf));
  let scopeMode = dateFrom(today()).getDate() >= 25 ? 'second' : 'first';
  let forecastGrouping = 'period';
  let incomeEdits = [];
  let incomeEditorRange = null;
  let incomeEditorFromBudget = false;
  const initialScopeDate = dateFrom(scopeMonth + (scopeMode === 'first' ? '-10' : '-25'));
  let budgetStart = (state.budgetPeriod && isDate(state.budgetPeriod.start)) ? state.budgetPeriod.start : iso(budgetCycle(initialScopeDate).start);
  let budgetEnd = (state.budgetPeriod && isDate(state.budgetPeriod.end) && state.budgetPeriod.end >= budgetStart && (dateFrom(state.budgetPeriod.end) - dateFrom(budgetStart)) / 86400000 <= 366) ? state.budgetPeriod.end : iso(budgetCycle(dateFrom(budgetStart)).end);
  function payOccurrence(item) { selectedOccurrence = item; openPayment(); }
  function dueLabel(item) { const date = iso(item.date), now = today(); return date < now ? 'Overdue' : date === now ? 'Due today' : shortDate.format(item.date); }
  function paidFor(flowId, date) { return (state.payments || []).filter(p => p.flowId === flowId && p.originalDate === date).reduce((sum, p) => sum + p.amount, 0); }
  function today() { const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Singapore", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date()); const part = type => parts.find(p => p.type === type).value; return part("year") + "-" + part("month") + "-" + part("day"); }
  function isCard(flow) { return flow.direction === 'expense' && (flow.kind === 'card' || (!flow.kind && /card/i.test(flow.category || ''))); }

  function byId(id) { return document.getElementById(id); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function isDate(value) { return /^\d{4}-\d{2}-\d{2}$/.test(value || '') && !Number.isNaN(new Date(value + 'T12:00:00').getTime()) && iso(new Date(value + 'T12:00:00')) === value; }
  function dateFrom(value) { const a = value.split('-').map(Number); return new Date(a[0], a[1] - 1, a[2], 12); }
  function iso(date) { return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0'); }
  function addDays(date, days) { const copy = new Date(date); copy.setDate(copy.getDate() + days); return copy; }
  function addMonths(date, months) { const first = new Date(date.getFullYear(), date.getMonth() + months, 1, 12); const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0, 12).getDate(); first.setDate(Math.min(date.getDate(), lastDay)); return first; }
  function monthKey(date) { return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0'); }
  function monthDay(year, month, day) { return new Date(year, month, Math.min(day, new Date(year, month + 1, 0, 12).getDate()), 12); }
  function number(value) { const n = Number(value); return Number.isFinite(n) ? n : 0; }
  function compact(value) { const sign = value < 0 ? '−' : ''; const a = Math.abs(value); return sign + (a >= 1000000 ? (a / 1000000).toFixed(1) + 'm' : a >= 1000 ? (a / 1000).toFixed(a >= 100000 ? 0 : 1) + 'k' : Math.round(a).toString()); }
  function showToast(message) { const el = byId('toast'); el.textContent = message; el.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.classList.remove('show'); }, 3100); }

  function validState(input) {
    return input && input.version === 1 && isDate(input.asOf) && Number.isFinite(Number(input.startingCash)) && Number.isFinite(Number(input.startingCash)) && (!input.payments || (Array.isArray(input.payments) && input.payments.every(p => p && typeof p.id === 'string' && typeof p.flowId === 'string' && isDate(p.originalDate) && isDate(p.paidOn) && Number.isFinite(p.amount) && p.amount > 0 && Number.isFinite(p.debtReduction) && p.debtReduction >= 0))) && Array.isArray(input.flows) && Array.isArray(input.balances) && input.flows.every(function (flow) {
      return flow && typeof flow.id === 'string' && typeof flow.name === 'string' && ['income', 'expense'].includes(flow.direction) && ['monthly', 'once'].includes(flow.schedule) && Number.isFinite(Number(flow.amount)) && Number(flow.amount) >= 0 && (flow.schedule === 'once' ? isDate(flow.date) : Number.isInteger(Number(flow.day)) && flow.day >= 1 && flow.day <= 31 && isDate(flow.start) && (!flow.end || (isDate(flow.end) && flow.end >= flow.start))) && (!flow.overrides || (typeof flow.overrides === 'object' && !Array.isArray(flow.overrides) && Object.entries(flow.overrides).every(([date, entry]) => isDate(date) && entry && isDate(entry.date) && Number.isFinite(entry.amount) && entry.amount >= 0)));
    }) && input.balances.every(function (balance) {
      return balance && typeof balance.id === 'string' && typeof balance.name === 'string' && ['asset', 'debt'].includes(balance.kind) && Number.isFinite(Number(balance.amount)) && Number(balance.amount) >= 0;
    });
  }
  function loadState() {
    try { const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)); if (validState(saved)) return saved; } catch (error) { /* Start from the documented seed if storage is unavailable. */ }
    return clone(DEFAULT_STATE);
  }
  function saveState() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch (error) { showToast('Could not save in this browser. Export a backup now.'); }
  }
  function uniqueId(prefix) { return prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8); }

  function eventAmount(flow, scenario) { return flow.direction === 'income' && scenario === 'conservative' && flow.lowAmount != null && flow.lowAmount !== '' ? number(flow.lowAmount) : number(flow.amount); }
  function buildEvents(start, end, scenario) {
    const items = [];
    state.flows.forEach(function (flow) {
      if (flow.paused) return;
      if (flow.schedule === 'once') {
        if (!isDate(flow.date)) return;
        const date = dateFrom(flow.date);
        items.push({ date: date, flow: flow, amount: eventAmount(flow, scenario) * (flow.direction === 'income' ? 1 : -1) });
        return;
      }
      if (!Number.isInteger(Number(flow.day)) || number(flow.day) < 1 || number(flow.day) > 31) return;
      const overrideDates = Object.keys(flow.overrides || {}).filter(isDate);
      const earliest = overrideDates.reduce((a, b) => b < a ? b : a, iso(start));
      const latest = overrideDates.reduce((a, b) => b > a ? b : a, iso(end));
      const month = new Date(dateFrom(earliest).getFullYear(), dateFrom(earliest).getMonth(), 1, 12);
      const finalMonth = new Date(dateFrom(latest).getFullYear(), dateFrom(latest).getMonth(), 1, 12);
      while (month <= finalMonth) {
        const date = monthDay(month.getFullYear(), month.getMonth(), number(flow.day));
        if ((!flow.start || !isDate(flow.start) || date >= dateFrom(flow.start)) && (!flow.end || !isDate(flow.end) || date <= dateFrom(flow.end))) {
          items.push({ date: date, flow: flow, amount: eventAmount(flow, scenario) * (flow.direction === 'income' ? 1 : -1) });
        }
        month.setMonth(month.getMonth() + 1);
      }
    });
    const adjusted = items.map(function (item) {
      item.originalDate = iso(item.date);
      const override = (item.flow.overrides || {})[item.originalDate];
      if (override) {
        item.skipped = !!override.skip;
        if (isDate(override.date)) item.date = dateFrom(override.date);
        if (Number.isFinite(override.amount)) item.amount = override.amount * (item.flow.direction === 'income' ? 1 : -1);
        if (item.skipped) item.amount = 0;
        item.adjusted = true;
      }
      const paidAmount = paidFor(item.flow.id, item.originalDate);
      if (item.flow.direction === 'expense' && paidAmount > 0) {
        item.paidAmount = paidAmount;
        const remaining = Math.max(0, Math.abs(item.amount) - paidAmount);
        item.paid = remaining === 0; item.partial = remaining > 0;
        item.amount = -remaining;
      }
      return item;
    }).filter(item => item.date >= start && item.date <= end);
    adjusted.sort(function (a, b) { return a.date - b.date || (a.amount < 0) - (b.amount < 0) || a.flow.name.localeCompare(b.flow.name); });
    return adjusted;
  }

  function forecast() {
    const asOf = dateFrom(state.asOf);
    const start = addDays(asOf, 1);
    const end = addMonths(asOf, number(state.horizon) || 6);
    const events = buildEvents(start, end, state.scenario);
    const daily = [{ date: asOf, balance: number(state.startingCash) }];
    const eventRows = [];
    let balance = number(state.startingCash);
    let min = { date: asOf, balance: balance };
    let position = 0;
    while (position < events.length) {
      const day = iso(events[position].date);
      while (position < events.length && iso(events[position].date) === day) {
        balance += events[position].amount;
        eventRows.push(Object.assign({}, events[position], { balance: balance }));
        position++;
      }
      daily.push({ date: dateFrom(day), balance: balance });
      if (balance < min.balance) min = { date: dateFrom(day), balance: balance };
    }
    daily.push({ date: end, balance: balance });
    const monthly = [];
    let cursor = new Date(start.getFullYear(), start.getMonth(), 1, 12);
    let rolling = number(state.startingCash);
    while (cursor <= end) {
      const key = monthKey(cursor);
      const thisMonth = events.filter(function (item) { return monthKey(item.date) === key; });
      let income = 0, outgo = 0, cards = 0, low = rolling, index = 0;
      while (index < thisMonth.length) {
        const day = iso(thisMonth[index].date);
        while (index < thisMonth.length && iso(thisMonth[index].date) === day) {
          const amount = thisMonth[index].amount;
          rolling += amount;
          if (amount > 0) income += amount; else outgo -= amount;
          if (isCard(thisMonth[index].flow)) cards -= amount;
          index++;
        }
        low = Math.min(low, rolling);
      }
      monthly.push({ date: new Date(cursor), income: income, outgo: outgo, cards: cards, low: low, endBalance: rolling });
      cursor.setMonth(cursor.getMonth() + 1);
    }
    return { asOf: asOf, end: end, events: eventRows, daily: daily, min: min, monthly: monthly };
  }

  function cell(row, text, className, label) { const td = document.createElement('td'); td.textContent = text; if (className) td.className = className; if (label) td.dataset.label = label; row.appendChild(td); return td; }
  function renderSummary(result) {
    byId('metric-cash').textContent = peso0.format(number(state.startingCash));
    byId('metric-cash-context').textContent = (state.cashUpdatedOn ? 'Updated ' + shortDate.format(dateFrom(state.cashUpdatedOn)) + ' · recorded payments included' : 'As of ' + shortDate.format(result.asOf));
    const low = byId('metric-low');
    low.textContent = peso0.format(result.min.balance);
    low.classList.toggle('negative', result.min.balance < 0);
    byId('metric-low-context').textContent = 'Around ' + shortDate.format(result.min.date) + ' · ' + (state.scenario === 'average' ? 'average' : 'low-pay') + ' scenario';
    const debts = state.balances.filter(function (balance) { return balance.kind === 'debt'; }).reduce(function (sum, balance) { return sum + number(balance.amount); }, 0);
    byId('metric-debt').textContent = peso0.format(debts);
    const notice = byId('forecast-notice');
    notice.classList.add('show');
    notice.classList.toggle('ok', result.min.balance >= 5000);
    if (result.min.balance < 0) notice.textContent = 'Projected shortfall: ' + peso0.format(Math.abs(result.min.balance)) + ' around ' + shortDate.format(result.min.date) + '. Adjust an income or payment entry before that date.';
    else if (result.min.balance < 5000) notice.textContent = 'Thin cash cushion: the forecast falls to ' + peso0.format(result.min.balance) + ' around ' + shortDate.format(result.min.date) + '. This assumes all listed dates and amounts hold.';
    else notice.textContent = 'No shortfall in the listed cash flows. Unlisted spending and your card’s next actual required amount could change this forecast.';
  }
  function renderTables(result) {
    const monthlyBody = byId('monthly-body'); monthlyBody.replaceChildren();
    byId('forecast-range-label').textContent = forecastGrouping === 'period' ? 'Period' : 'Month';
    const ranges = forecastGrouping === 'month' ? result.monthly : forecastPeriodRows(result);
    ranges.forEach(function (item) {
      const row = document.createElement('tr');
      cell(row, item.label || monthName.format(item.date), '', forecastGrouping === 'period' ? 'Period' : 'Month'); cell(row, peso2.format(item.income), '', 'Income'); cell(row, peso2.format(item.outgo - item.cards), '', 'Bills & other');
      cell(row, peso2.format(item.cards), 'card-value', 'Card payments');
      cell(row, peso2.format(item.low), item.low < 0 ? 'negative' : 'muted-cell', 'Lowest cash');
      cell(row, peso2.format(item.endBalance), item.endBalance < 0 ? 'negative' : '', 'End cash');
      monthlyBody.appendChild(row);
    });
    const upcomingBody = byId('upcoming-body'); upcomingBody.replaceChildren();
    const monthSelect = byId('activity-month'), previousMonth = monthSelect.value;
    monthSelect.replaceChildren(new Option('All forecast months', 'all'));
    result.monthly.forEach(item => monthSelect.add(new Option(monthName.format(item.date), monthKey(item.date))));
    monthSelect.value = Array.from(monthSelect.options).some(o => o.value === previousMonth) ? previousMonth : 'all';
    const periodSelect = byId('activity-period'), previousPeriod = periodSelect.value;
    periodSelect.replaceChildren(new Option('All payday periods', 'all'));
    forecastPeriodRows(result).forEach(item => periodSelect.add(new Option(item.label.replace('\n', ' · '), item.key)));
    periodSelect.value = Array.from(periodSelect.options).some(o => o.value === previousPeriod) ? previousPeriod : 'all';
    const filter = byId('activity-filter').value;
    const visible = result.events.filter(item => (periodSelect.value === 'all' || budgetCycle(item.date).key === periodSelect.value) && (monthSelect.value === 'all' || monthKey(item.date) === monthSelect.value) && (filter === 'all' || (filter === 'card' ? isCard(item.flow) : item.flow.direction === filter)));
    visible.forEach(function (item) {
      const row = document.createElement('tr');
      cell(row, shortDate.format(item.date), '', 'Date');
      const nameCell = cell(row, '', '', 'Item');
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'calendar-edit'; edit.textContent = item.flow.name + (item.paid ? ' · paid' : item.partial ? ' · part paid' : item.skipped ? ' · skipped' : item.adjusted ? ' · adjusted' : '') + (item.flow.confidence === 'estimate' ? ' · estimate' : ''); edit.addEventListener('click', () => openOccurrence(item)); nameCell.append(edit);
      if (item.flow.direction === 'expense' && !item.paid && !item.skipped && item.amount < 0) { const pay = document.createElement('button'); pay.type = 'button'; pay.className = 'button calendar-pay'; pay.textContent = item.partial ? 'Pay remaining' : 'Pay'; pay.setAttribute('aria-label', 'Record payment for ' + item.flow.name); pay.addEventListener('click', () => payOccurrence(item)); nameCell.append(pay); }
      cell(row, isCard(item.flow) ? 'Card payment' : item.flow.category || (item.amount > 0 ? 'Income' : 'Expense'), 'muted-cell', 'Type');
      cell(row, (item.amount > 0 ? '+' : '−') + peso2.format(Math.abs(item.amount)), item.amount > 0 ? 'amount-in' : 'amount-out', 'Cash change');
      cell(row, peso2.format(item.balance), item.balance < 0 ? 'negative' : '', 'Balance after');
      upcomingBody.appendChild(row);
    });
    if (!visible.length) { const row = document.createElement('tr'); row.className = 'empty-row'; cell(row, 'No activity matches this view. Change the filters or add an entry.', ''); upcomingBody.appendChild(row); upcomingBody.firstChild.firstChild.colSpan = 5; }
  }

  const svgNS = 'http://www.w3.org/2000/svg';
  function svgElement(name, attributes) { const el = document.createElementNS(svgNS, name); Object.keys(attributes || {}).forEach(function (key) { el.setAttribute(key, attributes[key]); }); return el; }
  function drawChart(result) {
    const svg = byId('cash-chart'); svg.replaceChildren();
    const width = Math.max(320, svg.clientWidth || 800);
    const height = svg.clientHeight || 260;
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    const left = width < 500 ? 47 : 58, right = 13, top = 20, bottom = 33;
    const plotW = width - left - right, plotH = height - top - bottom;
    const values = result.daily.map(function (point) { return point.balance; }).concat([0]);
    let minY = Math.min.apply(null, values), maxY = Math.max.apply(null, values);
    const pad = Math.max(2500, (maxY - minY) * .13); minY -= pad; maxY += pad;
    const startTime = result.asOf.getTime(), endTime = result.end.getTime();
    const x = function (date) { return left + ((date.getTime() - startTime) / Math.max(1, endTime - startTime)) * plotW; };
    const y = function (value) { return top + (maxY - value) / (maxY - minY) * plotH; };
    for (let index = 0; index <= 4; index++) {
      const value = minY + (maxY - minY) * index / 4;
      const py = y(value);
      svg.appendChild(svgElement('line', { x1: left, y1: py, x2: width - right, y2: py, stroke: 'var(--grid)', 'stroke-width': 1 }));
      const label = svgElement('text', { x: left - 7, y: py + 4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 11 });
      label.textContent = compact(value); svg.appendChild(label);
    }
    if (minY < 0 && maxY > 0) svg.appendChild(svgElement('line', { x1: left, y1: y(0), x2: width - right, y2: y(0), stroke: 'var(--red)', 'stroke-width': 1.5, 'stroke-dasharray': '4 4' }));
    const ticks = width < 500 ? 3 : 6;
    for (let index = 0; index <= ticks; index++) {
      const date = new Date(startTime + (endTime - startTime) * index / ticks);
      const label = svgElement('text', { x: x(date), y: height - 8, 'text-anchor': index === 0 ? 'start' : index === ticks ? 'end' : 'middle', fill: 'var(--muted)', 'font-size': 11 });
      label.textContent = new Intl.DateTimeFormat('en-PH', { month: 'short', year: ticks <= 3 ? '2-digit' : undefined }).format(date); svg.appendChild(label);
    }
    const points = result.daily.map(function (point) { return x(point.date).toFixed(1) + ',' + y(point.balance).toFixed(1); });
    const path = svgElement('polyline', { points: points.join(' '), fill: 'none', stroke: 'var(--accent)', 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }); svg.appendChild(path);
    const lowDot = svgElement('circle', { cx: x(result.min.date), cy: y(result.min.balance), r: 5, fill: result.min.balance < 0 ? 'var(--red)' : 'var(--accent)', stroke: 'var(--surface)', 'stroke-width': 2 });
    const title = svgElement('title'); title.textContent = 'Lowest balance ' + peso0.format(result.min.balance) + ' on ' + shortDate.format(result.min.date); lowDot.appendChild(title); svg.appendChild(lowDot);
    svg.setAttribute('aria-label', 'Projected cash from ' + shortDate.format(result.asOf) + ' to ' + shortDate.format(result.end) + '. Lowest balance ' + peso0.format(result.min.balance) + ' around ' + shortDate.format(result.min.date) + '.');
    byId('chart-range').textContent = shortDate.format(result.asOf) + ' – ' + shortDate.format(result.end);
  }

  function scheduleLabel(flow) {
    if (flow.schedule === 'once') return isDate(flow.date) ? shortDate.format(dateFrom(flow.date)) : 'Date missing';
    let label = 'Monthly on day ' + flow.day;
    if (flow.end && isDate(flow.end)) label += ' · ends ' + shortDate.format(dateFrom(flow.end));
    return label;
  }
  function renderFlowGroups() {
    const groups = [
      { id: 'income-list', flows: state.flows.filter(function (flow) { return flow.direction === 'income'; }) },
      { id: 'recurring-list', flows: state.flows.filter(function (flow) { return flow.direction === 'expense' && !isCard(flow) && flow.schedule === 'monthly'; }) },
      { id: 'one-time-list', flows: state.flows.filter(function (flow) { return flow.direction === 'expense' && !isCard(flow) && flow.schedule === 'once'; }) }
    ];
    groups.push({ id: 'card-list', flows: state.flows.filter(isCard) });
    const query = byId('flow-search').value.toLowerCase();
    groups.forEach(function (group) {
      if (group.id !== 'card-list') group.flows = group.flows.filter(flow => (flow.name + ' ' + flow.category).toLowerCase().includes(query));
      const container = byId(group.id); container.replaceChildren();
      if (!group.flows.length) { const empty = document.createElement('div'); empty.className = 'empty-card'; empty.textContent = 'Nothing here yet. Add a cash flow to include it.'; container.appendChild(empty); }
      group.flows.forEach(function (flow) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'flow-item' + (flow.paused ? ' paused' : ''); button.dataset.flowId = flow.id;
        const left = document.createElement('span'); const title = document.createElement('span'); title.className = 'item-title'; title.textContent = flow.name;
        const meta = document.createElement('span'); meta.className = 'item-meta'; meta.textContent = (flow.paused ? 'PAUSED · ' : '') + scheduleLabel(flow) + ' · ' + (flow.category || 'Uncategorized') + (Object.keys(flow.overrides || {}).length ? ' · individual changes' : '') + (flow.confidence === 'estimate' ? ' · estimate' : '');
        left.append(title, meta);
        const amount = document.createElement('span'); amount.className = 'item-amount' + (flow.direction === 'income' ? ' in' : '') + (flow.confidence === 'estimate' ? ' estimate' : ''); amount.textContent = (flow.direction === 'income' ? '+' : '−') + peso2.format(number(flow.amount));
        button.append(left, amount); container.appendChild(button);
      });
    });
  }
  function renderBalances() {
    const container = byId('balance-list'); container.replaceChildren();
    if (!state.balances.length) { const empty = document.createElement('div'); empty.className = 'empty-card'; empty.textContent = 'No balances yet. Add a debt or asset snapshot.'; container.appendChild(empty); }
    state.balances.forEach(function (balance) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'balance-item'; button.dataset.balanceId = balance.id;
      const left = document.createElement('span'); const title = document.createElement('span'); title.className = 'item-title'; title.textContent = balance.name;
      const meta = document.createElement('span'); meta.className = 'item-meta'; meta.textContent = (balance.kind === 'debt' ? 'Debt' : 'Asset') + ' · as of ' + (isDate(balance.asOf) ? shortDate.format(dateFrom(balance.asOf)) : 'unknown'); left.append(title, meta);
      const amount = document.createElement('span'); amount.className = 'item-amount'; amount.textContent = peso2.format(number(balance.amount)); button.append(left, amount); container.appendChild(button);
    });
  }
  function renderOverview(result) {
    const range = scopeRange(), scope = cashProjection(range.start, range.end);
    renderScopeSummary(range, scope);
    byId('overview-date').textContent = '10th & 25th payday cycles · ' + (state.scenario === 'average' ? 'Average pay' : 'Lower pay');
    const container = byId('overview-upcoming'); container.replaceChildren();
    const visible = scope.events.filter(item => !item.skipped && (upcomingFilter === 'all' || item.flow.direction === upcomingFilter));
    visible.forEach(item => {
      const row = document.createElement('div'); row.className = 'upcoming-item';
      const icon = document.createElement('span'); icon.className = 'entry-icon ' + (item.amount > 0 ? 'income-icon' : isCard(item.flow) ? 'card-icon' : 'expense-icon'); icon.append(uiIcon(flowIcon(item.flow)));
      const label = document.createElement('span'), name = document.createElement('strong'), date = document.createElement('span'); name.textContent = item.flow.name; date.className = 'item-meta'; date.textContent = (item.paid ? shortDate.format(item.date) + ' · Paid' : item.flow.direction === 'expense' ? dueLabel(item) : shortDate.format(item.date)) + ' · ' + (item.flow.schedule === 'monthly' ? 'Recurring' : 'One-time') + (isCard(item.flow) ? ' · Card payment' : '') + (item.partial ? ' · Part paid' : '') + (item.flow.confidence === 'estimate' ? ' · Estimate' : ''); label.append(name, date);
      const amount = document.createElement('strong'); amount.className = 'upcoming-amount'; amount.textContent = item.paid ? 'Paid ' + peso2.format(item.paidAmount) : (item.amount > 0 ? '+' : '−') + peso2.format(Math.abs(item.amount));
      const actions = document.createElement('div'); actions.className = 'bill-actions';
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'button bill-edit'; edit.textContent = 'Edit'; edit.setAttribute('aria-label', 'Edit ' + item.flow.name); edit.addEventListener('click', () => openOccurrence(item)); actions.append(edit);
      if (item.flow.direction === 'expense' && item.amount < 0) { const pay = document.createElement('button'); pay.type = 'button'; pay.className = 'button button-primary pay-button'; pay.textContent = item.partial ? 'Pay remaining' : 'Pay'; pay.setAttribute('aria-label', 'Record payment for ' + item.flow.name); pay.addEventListener('click', () => payOccurrence(item)); actions.append(pay); }
      row.append(icon, label, amount, actions); container.append(row);
    });
    if (!container.children.length) { const p = document.createElement('p'); p.className = 'empty-card'; p.textContent = scope.known ? 'No pending activity matches this selected range.' : 'This range ends before your cash snapshot. Historical cash cannot be reconstructed from this snapshot.'; container.append(p); }
    const recent = byId('overview-recent'), last = (state.payments || []).at(-1); recent.replaceChildren(); recent.hidden = !last;
    if (last) { const label = document.createElement('span'); label.textContent = 'Recorded ' + last.name + ' · ' + peso2.format(last.amount); const actions = document.createElement('div'); const history = document.createElement('a'); history.className = 'text-link'; history.href = '#plan'; history.textContent = 'History'; const undo = document.createElement('button'); undo.type = 'button'; undo.className = 'text-link'; undo.textContent = 'Undo'; undo.disabled = last.deductedCash && last.cashRevision !== (state.cashRevision || 0); undo.addEventListener('click', () => undoPayment(last.id)); actions.append(history, undo); recent.append(label, actions); }
  }
  function switchView() {
    const hash = location.hash.slice(1), view = ['overview', 'budget', 'forecast', 'cards', 'plan'].includes(hash) ? hash : ['cashflows', 'balances'].includes(hash) ? 'plan' : 'overview';
    document.querySelectorAll('[data-view]').forEach(panel => panel.hidden = panel.dataset.view !== view);
    document.querySelectorAll('[data-tab]').forEach(tab => { tab.classList.toggle('active', tab.dataset.tab === view); if (tab.dataset.tab === view) tab.setAttribute('aria-current', 'page'); else tab.removeAttribute('aria-current'); });
    if (hash === 'starting-point') byId('starting-point').open = true;
    window.scrollTo({ top: 0 });
    if (lastForecast) requestAnimationFrame(() => drawChart(lastForecast));
  }
  function render() {
    byId('as-of-date').value = state.asOf;
    byId('starting-cash').value = number(state.startingCash).toFixed(2);
    byId('scenario').value = state.scenario;
    byId('horizon').value = String(state.horizon);
    lastForecast = forecast();
    renderPaymentHistory(); renderOverview(lastForecast); renderCardSummary(lastForecast); renderSummary(lastForecast); renderTables(lastForecast); drawChart(lastForecast); renderFlowGroups(); renderBalances(); renderBudget();
  }

  function renderCardSummary(result) {
    const events = result.events.filter(item => isCard(item.flow) && !item.skipped && !item.paid && item.amount < 0);
    const next = events[0];
    byId('card-summary').replaceChildren();
    [['Next planned payment', next ? peso2.format(Math.abs(next.amount)) : 'None scheduled', next ? shortDate.format(next.date) : 'Add a card payment below'], ['Total across forecast', peso2.format(events.reduce((sum, item) => sum - item.amount, 0)), 'Already included in cash outgo']].forEach(([label, value, note]) => {
      const card = document.createElement('article'); card.className = 'metric';
      const p = document.createElement('p'); p.textContent = label;
      const strong = document.createElement('strong'); strong.textContent = value;
      const span = document.createElement('span'); span.textContent = note; card.append(p, strong, span);
      if (label === 'Next planned payment' && next && next.amount < 0) { const pay = document.createElement('button'); pay.type = 'button'; pay.className = 'button button-primary next-card-pay'; pay.textContent = 'Record payment'; pay.addEventListener('click', () => payOccurrence(next)); card.append(pay); }
      byId('card-summary').append(card);
    });
  }
  function openOccurrence(item) {
    selectedOccurrence = item;
    byId('occurrence-description').textContent = item.flow.name + ' · originally ' + shortDate.format(dateFrom(item.originalDate));
    byId('occurrence-date').value = iso(item.date);
    byId('occurrence-amount').value = item.skipped ? ((item.flow.overrides || {})[item.originalDate].amount ?? eventAmount(item.flow, state.scenario)) : Math.abs(item.amount);
    byId('record-payment').hidden = item.flow.direction !== 'expense' || item.paid || item.skipped;
    byId('record-payment').textContent = item.partial ? 'Record remaining payment' : 'Record payment';
    byId('occurrence-status').value = item.skipped ? 'skip' : 'active';
    byId('occurrence-dialog').showModal();
  }
  function toggleFlowFields() {
    const monthly = byId('flow-schedule').value === 'monthly';
    byId('once-date-wrap').hidden = monthly;
    byId('monthly-day-wrap').hidden = !monthly;
    byId('monthly-start-wrap').hidden = !monthly;
    byId('monthly-end-wrap').hidden = !monthly;
    byId('low-amount-wrap').hidden = byId('flow-direction').value !== 'income';
    byId('flow-date').required = !monthly;
    byId('flow-day').required = monthly;
    byId('flow-start').required = monthly;
  }
  function openFlow(id) {
    const flow = state.flows.find(function (item) { return item.id === id; });
    byId('flow-dialog-title').textContent = flow ? 'Edit cash flow' : 'Add cash flow';
    byId('flow-id').value = flow ? flow.id : '';
    byId('flow-name').value = flow ? flow.name : '';
    byId('flow-direction').value = flow ? flow.direction : 'expense';
    byId('flow-schedule').value = flow ? flow.schedule : 'monthly';
    byId('flow-amount').value = flow ? flow.amount : '';
    byId('flow-low-amount').value = flow && flow.lowAmount != null ? flow.lowAmount : '';
    byId('flow-date').value = flow && flow.date ? flow.date : iso(addDays(dateFrom(state.asOf), 1));
    byId('flow-day').value = flow && flow.day ? flow.day : 10;
    byId('flow-start').value = flow && flow.start ? flow.start : iso(addDays(dateFrom(state.asOf), 1));
    byId('flow-end').value = flow && flow.end ? flow.end : '';
    byId('flow-category').value = flow && flow.category ? flow.category : '';
    byId('flow-confidence').value = flow && flow.confidence ? flow.confidence : 'confirmed';
    byId('flow-note').value = flow && flow.note ? flow.note : '';
    byId('flow-kind').value = flow && isCard(flow) ? 'card' : 'regular';
    byId('flow-status').value = flow && flow.paused ? 'paused' : 'active';
    byId('duplicate-flow').hidden = !flow;
    byId('delete-flow').hidden = !flow;
    toggleFlowFields(); byId('flow-dialog').showModal(); byId('flow-name').focus();
  }
  function saveFlow(event) {
    event.preventDefault();
    const id = byId('flow-id').value || uniqueId('flow');
    const flow = { id: id, name: byId('flow-name').value.trim(), direction: byId('flow-direction').value, schedule: byId('flow-schedule').value, amount: number(byId('flow-amount').value), category: byId('flow-category').value.trim(), confidence: byId('flow-confidence').value, note: byId('flow-note').value.trim() };
    flow.kind = byId('flow-kind').value; flow.paused = byId('flow-status').value === 'paused';
    const existing = state.flows.find(item => item.id === id);
    if (existing && existing.overrides) flow.overrides = existing.overrides;
    if (flow.kind === 'card' && flow.direction !== 'expense') { showToast('A card payment must be money out.'); return; }
    if (!flow.name || flow.amount < 0) { showToast('Add a name and a valid amount.'); return; }
    if (flow.direction === 'income' && byId('flow-low-amount').value !== '') flow.lowAmount = number(byId('flow-low-amount').value);
    if (flow.schedule === 'once') { flow.date = byId('flow-date').value; if (!isDate(flow.date)) { showToast('Choose a valid date.'); return; } }
    else { flow.day = number(byId('flow-day').value); flow.start = byId('flow-start').value; flow.end = byId('flow-end').value; if (flow.day < 1 || flow.day > 31 || !isDate(flow.start) || (flow.end && (!isDate(flow.end) || flow.end < flow.start))) { showToast('Check the monthly schedule dates.'); return; } }
    const index = state.flows.findIndex(function (item) { return item.id === id; });
    if (index === -1) state.flows.push(flow); else state.flows[index] = flow;
    saveState(); byId('flow-dialog').close(); render(); showToast('Cash flow saved.');
  }
  function deleteFlow() {
    const id = byId('flow-id').value; if (!id) return;
    if (!window.confirm('Delete this cash flow? This will change the forecast.')) return;
    state.flows = state.flows.filter(function (item) { return item.id !== id; });
    saveState(); byId('flow-dialog').close(); render(); showToast('Cash flow deleted.');
  }
  function openBalance(id) {
    const balance = state.balances.find(function (item) { return item.id === id; });
    byId('balance-dialog-title').textContent = balance ? 'Edit balance' : 'Add balance';
    byId('balance-id').value = balance ? balance.id : '';
    byId('balance-name').value = balance ? balance.name : '';
    byId('balance-kind').value = balance ? balance.kind : 'debt';
    byId('balance-amount').value = balance ? balance.amount : '';
    byId('balance-date').value = balance && balance.asOf ? balance.asOf : state.asOf;
    byId('balance-note').value = balance && balance.note ? balance.note : '';
    byId('delete-balance').hidden = !balance;
    byId('balance-dialog').showModal(); byId('balance-name').focus();
  }
  function saveBalance(event) {
    event.preventDefault();
    const id = byId('balance-id').value || uniqueId('balance');
    const balance = { id: id, name: byId('balance-name').value.trim(), kind: byId('balance-kind').value, amount: number(byId('balance-amount').value), asOf: byId('balance-date').value, note: byId('balance-note').value.trim() };
    if (!balance.name || balance.amount < 0 || !isDate(balance.asOf)) { showToast('Check the balance details.'); return; }
    const index = state.balances.findIndex(function (item) { return item.id === id; });
    if (index === -1) state.balances.push(balance); else state.balances[index] = balance;
    saveState(); byId('balance-dialog').close(); render(); showToast('Balance saved.');
  }
  function deleteBalance() {
    const id = byId('balance-id').value; if (!id) return;
    if (!window.confirm('Delete this balance snapshot?')) return;
    state.balances = state.balances.filter(function (item) { return item.id !== id; });
    saveState(); byId('balance-dialog').close(); render(); showToast('Balance deleted.');
  }
  function exportData() {
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = 'money-map-backup-' + iso(new Date()) + '.json'; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000); showToast('Backup downloaded.');
  }
  async function importData(file) {
    if (!file) return;
    try {
      const candidate = JSON.parse(await file.text());
      if (!validState(candidate)) { showToast('That file is not a Money Map backup.'); return; }
      if (!window.confirm('Replace this browser’s current finance data with the imported backup?')) return;
      state = candidate; state.scenario = ['average', 'conservative'].includes(state.scenario) ? state.scenario : 'average'; state.horizon = [3, 6, 12].includes(number(state.horizon)) ? number(state.horizon) : 6;
      saveState(); render(); showToast('Backup imported.');
    } catch (error) { showToast('Could not read that backup file.'); }
  }

  byId('starting-form').addEventListener('submit', function (event) { event.preventDefault(); const date = byId('as-of-date').value, cash = number(byId('starting-cash').value); if (!isDate(date) || cash < 0) return; state.asOf = date; state.startingCash = cash; state.cashUpdatedOn = ''; state.cashRevision = (state.cashRevision || 0) + 1; saveState(); render(); showToast('Starting point updated.'); });
  byId('scenario').addEventListener('change', function () { state.scenario = this.value; saveState(); render(); });
  byId('horizon').addEventListener('change', function () { state.horizon = number(this.value); saveState(); render(); });
  byId('add-flow').addEventListener('click', function () { openFlow(); });
  byId('add-flow-top').addEventListener('click', function () { openFlow(); });
  byId('income-list').addEventListener('click', function (event) { const item = event.target.closest('[data-flow-id]'); if (item) openFlow(item.dataset.flowId); });
  byId('recurring-list').addEventListener('click', function (event) { const item = event.target.closest('[data-flow-id]'); if (item) openFlow(item.dataset.flowId); });
  byId('one-time-list').addEventListener('click', function (event) { const item = event.target.closest('[data-flow-id]'); if (item) openFlow(item.dataset.flowId); });
  byId('flow-direction').addEventListener('change', toggleFlowFields);
  byId('flow-schedule').addEventListener('change', toggleFlowFields);
  byId('flow-form').addEventListener('submit', saveFlow);
  byId('delete-flow').addEventListener('click', deleteFlow);
  byId('close-flow').addEventListener('click', function () { byId('flow-dialog').close(); });
  byId('cancel-flow').addEventListener('click', function () { byId('flow-dialog').close(); });
  byId('add-balance').addEventListener('click', function () { openBalance(); });
  byId('balance-list').addEventListener('click', function (event) { const item = event.target.closest('[data-balance-id]'); if (item) openBalance(item.dataset.balanceId); });
  byId('balance-form').addEventListener('submit', saveBalance);
  byId('delete-balance').addEventListener('click', deleteBalance);
  byId('close-balance').addEventListener('click', function () { byId('balance-dialog').close(); });
  byId('cancel-balance').addEventListener('click', function () { byId('balance-dialog').close(); });
  byId('export-data').addEventListener('click', exportData);
  byId('import-data').addEventListener('click', function () { byId('import-file').click(); });
  byId('import-file').addEventListener('change', function () { importData(this.files[0]); this.value = ''; });
  window.addEventListener('resize', function () { if (lastForecast) drawChart(lastForecast); });

  byId('card-list').addEventListener('click', event => { const item = event.target.closest('[data-flow-id]'); if (item) openFlow(item.dataset.flowId); });
  byId('flow-search').addEventListener('input', renderFlowGroups);
  byId('activity-filter').addEventListener('change', () => renderTables(lastForecast));
  byId('activity-month').addEventListener('change', () => renderTables(lastForecast));
  byId('activity-period').addEventListener('change', () => renderTables(lastForecast));
  document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => {
    openFlow(); const preset = button.dataset.preset;
    byId('flow-direction').value = preset === 'income' ? 'income' : 'expense';
    byId('flow-kind').value = preset === 'card' ? 'card' : 'regular';
    byId('flow-dialog-title').textContent = preset === 'card' ? 'Add card payment' : preset === 'income' ? 'Add income' : 'Add bill or expense';
    if (preset === 'card') { byId('flow-category').value = 'Credit card'; byId('flow-confidence').value = 'estimate'; }
    toggleFlowFields();
  }));
  byId('duplicate-flow').addEventListener('click', () => { byId('flow-id').value = ''; byId('flow-name').value += ' (copy)'; byId('flow-dialog-title').textContent = 'Duplicate entry'; byId('delete-flow').hidden = true; byId('duplicate-flow').hidden = true; showToast('Edit the copy, then save to add it.'); });
  byId('close-occurrence').addEventListener('click', () => byId('occurrence-dialog').close());
  byId('occurrence-series').addEventListener('click', () => { byId('occurrence-dialog').close(); openFlow(selectedOccurrence.flow.id); });
  byId('occurrence-reset').addEventListener('click', () => { const flow = selectedOccurrence.flow; if (flow.overrides) delete flow.overrides[selectedOccurrence.originalDate]; saveState(); byId('occurrence-dialog').close(); render(); showToast('Original schedule restored.'); });
  byId('occurrence-form').addEventListener('submit', event => {
    event.preventDefault(); const date = byId('occurrence-date').value, amount = Number(byId('occurrence-amount').value);
    if (!isDate(date) || !Number.isFinite(amount) || amount < 0) return;
    if (date <= state.asOf) { showToast('Choose a date after your cash snapshot so it appears in the forecast.'); return; }
    const flow = selectedOccurrence.flow; flow.overrides = flow.overrides || {};
    flow.overrides[selectedOccurrence.originalDate] = { date, amount, skip: byId('occurrence-status').value === 'skip' };
    saveState(); byId('occurrence-dialog').close(); render(); showToast('Only this occurrence was changed.');
  });
  function openPayment() {
    const item = selectedOccurrence;
    if (!item || item.flow.direction !== 'expense' || item.paid || item.skipped) return;
    byId('occurrence-dialog').close();
    byId('payment-description').textContent = item.flow.name + ' · scheduled ' + shortDate.format(dateFrom(item.originalDate)) + (item.partial ? ' · ' + peso2.format(item.paidAmount) + ' already recorded' : '');
    byId('payment-amount').value = Math.abs(item.amount).toFixed(2);
    byId('payment-date').value = today(); byId('payment-date').max = today();
    byId('payment-cash').value = 'deduct';
    const select = byId('payment-debt'); select.replaceChildren(new Option('Keep debt snapshots unchanged', ''));
    state.balances.filter(b => b.kind === 'debt').forEach(b => select.add(new Option(b.name + ' · ' + peso2.format(b.amount), b.id)));
    const links = { 'card-pay': 'card-balance' };
    select.value = state.balances.some(b => b.id === links[item.flow.id]) ? links[item.flow.id] : '';
    byId('payment-principal').value = select.value ? Math.abs(item.amount).toFixed(2) : '';
    document.querySelector('.payment-options').open = false;
    updatePaymentPreview(); byId('payment-dialog').showModal();
  }
  function updatePaymentPreview() {
    const amount = number(byId('payment-amount').value), deduct = byId('payment-cash').value === 'deduct';
    const remaining = Math.max(0, Math.abs(selectedOccurrence.amount) - amount);
    byId('payment-principal-wrap').hidden = !byId('payment-debt').value;
    byId('payment-principal').required = !!byId('payment-debt').value;
    byId('payment-principal').max = String(amount);
    const debt = state.balances.find(b => b.id === byId('payment-debt').value);
    byId('payment-preview').textContent = 'Cash after recording: ' + peso2.format(number(state.startingCash) - (deduct ? amount : 0)) + '. Remaining in this occurrence: ' + peso2.format(remaining) + '.' + (debt ? ' ' + debt.name + ' after payment: ' + peso2.format(number(debt.amount) - number(byId('payment-principal').value)) + '.' : ' Debt snapshots stay unchanged.');
  }
  function recordPayment(event) {
    event.preventDefault(); const item = selectedOccurrence;
    const amount = Number(byId('payment-amount').value), paidOn = byId('payment-date').value, deduct = byId('payment-cash').value === 'deduct';
    const debt = state.balances.find(b => b.id === byId('payment-debt').value);
    const reduction = debt ? Number(byId('payment-principal').value) : 0;
    if (!item || !state.flows.some(f => f.id === item.flow.id) || !Number.isFinite(amount) || amount <= 0 || !isDate(paidOn) || paidOn > today() || !Number.isFinite(reduction) || reduction < 0 || reduction > amount || (debt && reduction > Number(debt.amount))) { showToast('Check the amount, payment date, and debt reduction.'); return; }
    if (deduct && amount > number(state.startingCash)) { showToast('Payment exceeds your cash balance. Update your cash first, or choose already included if you recorded it before.'); return; }
    if (deduct && paidOn < state.asOf) { showToast('This predates your cash snapshot. Choose cash already includes this payment.'); return; }
    const original = (item.flow.overrides || {})[item.originalDate];
    const target = original && Number.isFinite(original.amount) ? original.amount : eventAmount(item.flow, state.scenario);
    if (paidFor(item.flow.id, item.originalDate) >= target) { showToast('This occurrence is already fully paid.'); return; }
    const record = { id: uniqueId('payment'), flowId: item.flow.id, name: item.flow.name, originalDate: item.originalDate, amount, paidOn, deductedCash: deduct, cashRevision: state.cashRevision || 0, previousCashUpdatedOn: state.cashUpdatedOn || '', debtId: debt ? debt.id : '', debtReduction: reduction, debtBefore: debt ? number(debt.amount) : null, previousDebtDate: debt ? debt.asOf : '' };
    const next = clone(state); next.payments = next.payments || []; next.payments.push(record);
    if (deduct) { next.startingCash = number(next.startingCash) - amount; next.cashUpdatedOn = paidOn; }
    if (debt && reduction > 0) { const updated = next.balances.find(b => b.id === debt.id); updated.amount -= reduction; updated.asOf = paidOn; }
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (error) { showToast('Payment was not recorded. Storage is unavailable; export a backup first.'); return; }
    state = next; byId('payment-dialog').close(); render(); showToast('Payment recorded. Cash and forecast updated.');
  }
  function renderPaymentHistory() {
    const container = byId('payment-history'); container.replaceChildren();
    const payments = state.payments || [];
    if (!payments.length) { const p = document.createElement('p'); p.className = 'empty-card'; p.textContent = 'No recorded payments yet. Tap a scheduled expense, then Record payment.'; container.append(p); return; }
    payments.slice().reverse().forEach(p => {
      const row = document.createElement('div'); row.className = 'payment-row';
      const label = document.createElement('div'), title = document.createElement('strong'), note = document.createElement('span'); title.textContent = p.name; note.className = 'item-meta'; note.textContent = shortDate.format(dateFrom(p.paidOn)) + ' · ' + (p.deductedCash ? 'Cash deducted' : 'Already in cash') + (p.debtReduction ? ' · debt reduced ' + peso2.format(p.debtReduction) : ''); label.append(title, note);
      const actions = document.createElement('div'); actions.className = 'payment-row-actions'; const amount = document.createElement('strong'); amount.textContent = peso2.format(p.amount); const undo = document.createElement('button'); undo.className = 'text-link'; undo.type = 'button'; undo.textContent = 'Undo'; undo.addEventListener('click', () => undoPayment(p.id));
      const newer = payments.slice(payments.indexOf(p) + 1).some(q => (p.deductedCash && q.deductedCash) || (p.debtId && q.debtId === p.debtId));
      undo.disabled = newer || (p.deductedCash && p.cashRevision !== (state.cashRevision || 0)); undo.title = undo.disabled ? 'Undo newer payments first. Cash included in a newer snapshot is reconciled manually.' : 'Reverse this recorded payment'; actions.append(amount, undo); row.append(label, actions); container.append(row);
    });
  }
  function undoPayment(id) {
    const p = (state.payments || []).find(p => p.id === id); if (!p) return;
    if (p.deductedCash && p.cashRevision !== (state.cashRevision || 0)) { showToast('A newer cash snapshot includes this payment. Adjust the snapshot manually.'); return; }
    const newer = (state.payments || []).slice((state.payments || []).indexOf(p) + 1).some(q => (p.deductedCash && q.deductedCash) || (p.debtId && q.debtId === p.debtId));
    if (newer) { showToast('Undo newer payments affecting this cash or debt first.'); return; }
    const debt = state.balances.find(b => b.id === p.debtId);
    if (p.debtReduction && (!debt || Math.abs(number(debt.amount) - (p.debtBefore - p.debtReduction)) > .005)) { showToast('This debt snapshot changed after the payment. Correct its balance manually first.'); return; }
    const next = clone(state); next.payments = next.payments.filter(q => q.id !== id);
    if (p.deductedCash) { next.startingCash = number(next.startingCash) + p.amount; next.cashUpdatedOn = p.previousCashUpdatedOn; }
    if (debt && p.debtReduction) { const updated = next.balances.find(b => b.id === debt.id); updated.amount = p.debtBefore; updated.asOf = p.previousDebtDate; }
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (error) { showToast('Could not undo. Your payment record is unchanged.'); return; }
    state = next; render(); showToast('Payment undone. Its scheduled amount is restored.');
  }
  byId('record-payment').addEventListener('click', openPayment);
  byId('payment-form').addEventListener('submit', recordPayment);
  byId('close-payment').addEventListener('click', () => byId('payment-dialog').close());
  byId('cancel-payment').addEventListener('click', () => byId('payment-dialog').close());
  byId('payment-amount').addEventListener('input', () => { if (byId('payment-debt').value && !isCard(selectedOccurrence.flow)) byId('payment-principal').value = byId('payment-amount').value; });
  byId('payment-debt').addEventListener('change', () => { byId('payment-principal').value = byId('payment-debt').value && !isCard(selectedOccurrence.flow) ? byId('payment-amount').value : ''; updatePaymentPreview(); });
  ['payment-amount', 'payment-cash', 'payment-debt', 'payment-principal'].forEach(id => byId(id).addEventListener('input', updatePaymentPreview));
  byId('upcoming-filters').addEventListener('click', event => { const button = event.target.closest('[data-upcoming]'); if (!button) return; upcomingFilter = button.dataset.upcoming; document.querySelectorAll('[data-upcoming]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); renderOverview(lastForecast); });
  function budgetKey() { return budgetStart + ':' + budgetEnd; }
  function validBudgetDraft(draft) {
    const positive = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    return draft && (draft.income === null || positive(draft.income)) && positive(draft.carry) && draft.bills && typeof draft.bills === 'object' && !Array.isArray(draft.bills) && Object.values(draft.bills).every(b => b && typeof b.included === 'boolean' && (b.amount === null || positive(b.amount)) && (b.paidAtEdit === undefined || positive(b.paidAtEdit))) && Array.isArray(draft.extras) && draft.extras.every(e => e && typeof e.id === 'string' && typeof e.name === 'string' && positive(e.amount));
  }
  function budgetDraft() {
    // Planning drafts are separate from cash snapshots, payments, and forecast inputs.
    if (!state.cashPlans || typeof state.cashPlans !== 'object' || Array.isArray(state.cashPlans)) state.cashPlans = {};
    const key = budgetKey();
    if (!validBudgetDraft(state.cashPlans[key])) state.cashPlans[key] = { income: null, carry: 0, bills: {}, extras: [] };
    return state.cashPlans[key];
  }
  function budgetEvents() { return buildEvents(dateFrom(budgetStart), dateFrom(budgetEnd), state.scenario).filter(e => !e.skipped); }
  function saveBudget() {
    state.budgetPeriod = { start: budgetStart, end: budgetEnd };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); byId('budget-save-note').textContent = 'Draft saved in this browser · included in backups. Draft income, bill amounts, and extras do not change your forecast or record payments.'; }
    catch (error) { byId('budget-save-note').textContent = 'Could not save this draft. Keep this page open and export a backup from Plan.'; }
  }
  function budgetBillKey(item) { return item.flow.id + ':' + item.originalDate; }
  function budgetBillAmount(item, edit) {
    if (item.paid) return 0;
    return edit && edit.amount !== null ? Math.max(0, edit.amount - ((item.paidAmount || 0) - (edit.paidAtEdit || 0))) : Math.abs(item.amount);
  }
  function budgetCycle(date) {
    const year = date.getFullYear(), month = date.getMonth(), day = date.getDate(), first = day >= 10 && day < 25;
    const start = new Date(year, month - (day < 10 ? 1 : 0), first ? 10 : 25, 12);
    const end = first ? new Date(year, month, 24, 12) : new Date(start.getFullYear(), start.getMonth() + 1, 9, 12);
    return { key: iso(start), start, end, type: first ? 'first' : 'second', name: first ? '1st period' : '2nd period' };
  }
  function scopeRange(mode = scopeMode) {
    const date = dateFrom(scopeMonth + '-01'), y = date.getFullYear(), m = date.getMonth();
    if (mode === 'month') return { start: date, end: new Date(y, m + 1, 0, 12), label: monthName.format(date) + ' · monthly overview' };
    const cycle = budgetCycle(new Date(y, m, mode === 'first' ? 10 : 25, 12));
    return { ...cycle, label: monthName.format(date) + ' · ' + cycle.name };
  }
  function cashProjection(start, end) {
    const snapshot = dateFrom(state.asOf), known = end > snapshot, effectiveStart = start > snapshot ? start : addDays(snapshot, 1);
    let opening = number(state.startingCash);
    if (start > addDays(snapshot, 1)) opening += buildEvents(addDays(snapshot, 1), addDays(start, -1), state.scenario).reduce((sum, e) => sum + e.amount, 0);
    const events = known ? buildEvents(effectiveStart, end, state.scenario).filter(e => !e.skipped) : [];
    const income = events.filter(e => e.flow.direction === 'income').reduce((sum, e) => sum + e.amount, 0);
    const expenses = events.filter(e => e.flow.direction === 'expense').reduce((sum, e) => sum - e.amount, 0);
    const cards = events.filter(e => isCard(e.flow)).reduce((sum, e) => sum - e.amount, 0);
    const recurring = events.filter(e => e.flow.direction === 'expense' && e.flow.schedule === 'monthly').reduce((sum, e) => sum - e.amount, 0);
    let balance = opening, low = opening;
    events.forEach((e, index) => { balance += e.amount; if (!events[index+1] || iso(events[index+1].date) !== iso(e.date)) low = Math.min(low, balance); });
    return { known, partial: start <= snapshot, effectiveStart, opening, income, expenses, cards, recurring, once: expenses - recurring, available: opening + income, left: opening + income - expenses, low, events };
  }
  function forecastPeriodRows(result) {
    const rows = []; let cycle = budgetCycle(addDays(result.asOf, 1));
    while (cycle.start <= result.end) {
      const end = cycle.end < result.end ? cycle.end : result.end, projection = cashProjection(cycle.start, end);
      rows.push({ key: cycle.key, label: monthName.format(cycle.start) + ' · ' + cycle.name + '\n' + shortDate.format(projection.effectiveStart) + ' – ' + shortDate.format(end), income: projection.income, outgo: projection.expenses, cards: projection.cards, low: projection.low, endBalance: projection.left });
      cycle = budgetCycle(addDays(cycle.end, 1));
    }
    return rows;
  }
  function appendMoneyRow(container, label, value, className = '') {
    const row = document.createElement('div'), name = document.createElement('span'), amount = document.createElement('strong');
    name.textContent = label; amount.textContent = value === null ? '—' : peso2.format(value); if (value < 0) amount.classList.add('negative'); row.className = className; row.append(name, amount); container.append(row);
  }
  function renderScopeSummary(range, projection) {
    byId('scope-month').value = scopeMonth;
    document.querySelectorAll('[data-scope]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scope === scopeMode)));
    byId('scope-title').textContent = range.label;
    byId('scope-dates').textContent = shortDate.format(range.start) + ' – ' + shortDate.format(range.end);
    const values = { opening: projection.opening, income: projection.income, expenses: projection.expenses, available: projection.available, left: projection.left };
    Object.entries(values).forEach(([key, value]) => { byId('scope-' + key).textContent = projection.known ? peso2.format(value) : '—'; byId('scope-' + key).classList.toggle('negative', projection.known && value < 0); });
    byId('scope-opening-label').textContent = projection.partial ? 'Cash snapshot brought forward' : 'Projected cash brought forward';
    byId('scope-context').textContent = !projection.known ? 'This range predates your cash snapshot; historical balances are unavailable.' : (projection.partial ? 'Remaining activity after your ' + shortDate.format(dateFrom(state.asOf)) + ' cash snapshot. Earlier income and payments are already included in that cash.' : 'Cash brought forward is projected from your ' + shortDate.format(dateFrom(state.asOf)) + ' snapshot and earlier pending activity.') + ' Includes card payments. Cash plan drafts are separate.';
    byId('scope-activity-title').textContent = scopeMode === 'month' ? 'This month’s expenses & income' : 'This period’s expenses & income';
    byId('scope-plan').textContent = scopeMode === 'month' ? 'Plan this month' : 'Plan this period';
    byId('scope-update-pay').textContent = scopeMode === 'month' ? 'Update this month’s payday incomes' : 'Update income for this period';
    byId('scope-update-pay').disabled = !projection.events.some(e => e.flow.direction === 'income');
    const breakdown = byId('scope-breakdown'); breakdown.replaceChildren();
    if (projection.known) {
      const caption = document.createElement('p'); caption.className = 'eyebrow'; caption.textContent = 'PENDING EXPENSE BREAKDOWN'; breakdown.append(caption);
      const totals = document.createElement('div'); totals.className = 'scope-type-totals';
      appendMoneyRow(totals, '↻ Recurring', projection.recurring); appendMoneyRow(totals, '1× One-time', projection.once); breakdown.append(totals);
      const categories = new Map(); projection.events.filter(e => e.flow.direction === 'expense' && e.amount < 0).forEach(e => { const category = isCard(e.flow) ? 'Card payments' : e.flow.category || 'Other expenses'; categories.set(category, (categories.get(category) || 0) - e.amount); });
      const list = document.createElement('div'); list.className = 'month-preview'; [...categories].sort((a,b) => b[1]-a[1]).forEach(([name, amount]) => appendMoneyRow(list, name, amount)); breakdown.append(list);
    }
    const monthRange = scopeRange('month'), month = cashProjection(monthRange.start, monthRange.end), panel = byId('overview-month-summary'); panel.replaceChildren();
    byId('overview-month-title').textContent = monthName.format(monthRange.start) + ' at a glance';
    [['Cash brought forward', month.opening], ['+ Income', month.income], ['= Available cash', month.available], ['− All pending expenses', month.expenses], ['Projected month-end cash', month.left]].forEach(([name, value]) => appendMoneyRow(panel, name, month.known ? value : null));
    byId('overview-month-context').textContent = month.partial ? 'Remaining month after the cash snapshot. Previously received income is already in cash.' : 'Calendar-month totals use only dates in this month. The 2nd payday period also covers bills through next month’s 9th.';
  }
  function includedBudgetAmount(item) {
    const edit = budgetDraft().bills[budgetBillKey(item)];
    return edit && !edit.included ? 0 : budgetBillAmount(item, edit);
  }
  function updateBudgetGroupTotals() {
    let recurring = 0, once = 0;
    budgetGroups.forEach(group => {
      let groupTotal = 0;
      ['monthly', 'once'].forEach(schedule => {
        const subtotal = group.items.filter(e => e.flow.schedule === schedule).reduce((sum, e) => sum + includedBudgetAmount(e), 0);
        if (group.subtotals[schedule]) group.subtotals[schedule].textContent = peso2.format(subtotal);
        if (schedule === 'monthly') recurring += subtotal; else once += subtotal;
        groupTotal += subtotal;
      });
      group.total.textContent = peso2.format(groupTotal);
    });
    byId('budget-recurring-total').textContent = peso2.format(recurring);
    byId('budget-once-total').textContent = peso2.format(once);
  }
  function renderBudgetPeriodSelection() {
    const start = dateFrom(budgetStart), end = dateFrom(budgetEnd), cycle = budgetCycle(start);
    byId('budget-month-title').textContent = new Intl.DateTimeFormat('en-PH', { month: 'long', year: 'numeric' }).format(start);
    const wholeMonth = start.getDate() === 1 && iso(new Date(start.getFullYear(), start.getMonth()+1, 0, 12)) === budgetEnd;
    const mode = wholeMonth ? 'month' : cycle.key === budgetStart && iso(cycle.end) === budgetEnd ? cycle.type : 'custom';
    document.querySelectorAll('[data-budget-period]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.budgetPeriod === mode));
      const y = start.getFullYear(), m = start.getMonth(), kind = button.dataset.budgetPeriod;
      const from = new Date(y, m, kind === 'first' ? 10 : kind === 'second' ? 25 : 1, 12);
      const through = kind === 'first' ? new Date(y, m, 24, 12) : kind === 'second' ? new Date(y, m + 1, 9, 12) : new Date(y, m + 1, 0, 12);
      const format = new Intl.DateTimeFormat('en-PH', {month:'short',day:'numeric'});
      button.querySelector('span').textContent = format.format(from) + ' – ' + format.format(through);
    });
    byId('budget-period-selection').textContent = (mode === 'month' ? 'Whole month' : mode === 'custom' ? 'Custom period' : cycle.name + ' · ' + (mode === 'first' ? '10th payday' : '25th payday')) + ' · ' + shortDate.format(start) + ' – ' + shortDate.format(end);
  }
  function budgetTotals() {
    const draft = budgetDraft(), events = budgetEvents();
    const scheduledIncome = events.filter(e => e.flow.direction === 'income').reduce((sum, e) => sum + e.amount, 0);
    const income = draft.income === null ? scheduledIncome : draft.income;
    const bills = events.filter(e => e.flow.direction === 'expense' && !e.paid).reduce((sum, e) => {
      const edit = draft.bills[budgetBillKey(e)];
      return sum + (edit && !edit.included ? 0 : budgetBillAmount(e, edit));
    }, 0);
    const extras = draft.extras.reduce((sum, e) => sum + e.amount, 0), available = income + draft.carry;
    return { scheduledIncome, income, bills, extras, available, remaining: available - bills - extras };
  }
  function updateBudgetTotals() {
    const totals = budgetTotals(), shortfall = totals.remaining < 0;
    byId('budget-remaining').textContent = peso2.format(Math.abs(totals.remaining));
    byId('budget-result-label').textContent = shortfall ? 'Cash shortfall' : 'Cash left after bills';
    byId('budget-remaining').classList.toggle('negative', shortfall);
    byId('budget-bottom-amount').textContent = peso2.format(Math.abs(totals.remaining));
    byId('budget-bottom-label').textContent = shortfall ? 'Shortfall' : 'Cash left';
    byId('budget-bottom-amount').classList.toggle('negative', shortfall);
    byId('budget-result-note').textContent = shortfall ? 'Your planned expenses exceed available cash by this amount.' : 'Unallocated cash for ' + shortDate.format(dateFrom(budgetStart)) + ' – ' + shortDate.format(dateFrom(budgetEnd));
    byId('budget-available').textContent = peso2.format(totals.available);
    byId('budget-out').textContent = peso2.format(totals.bills + totals.extras);
    byId('budget-bills-total').textContent = peso2.format(totals.bills);
    byId('budget-extras-total').textContent = peso2.format(totals.extras);
    updateBudgetGroupTotals();
    byId('budget-income-note').textContent = 'Scheduled pay: ' + peso2.format(totals.scheduledIncome) + ' (' + (state.scenario === 'conservative' ? 'lowest observed pay' : 'average pay') + '). Enter the net amount you expect or received. Carry-over starts at zero to avoid counting your cash twice.';
  }
  function budgetAmountInput(value, label, onInput) {
    const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.step = '0.01'; input.inputMode = 'decimal'; input.value = value.toFixed(2); input.setAttribute('aria-label', label);
    input.addEventListener('input', () => { if (input.value === '' || !input.validity.valid) return; onInput(Number(input.value)); saveBudget(); updateBudgetTotals(); });
    return input;
  }
  function renderBudgetExtras() {
    const draft = budgetDraft(), container = byId('budget-extras'); container.replaceChildren();
    if (!draft.extras.length) { const p = document.createElement('p'); p.className = 'budget-empty'; p.textContent = 'No extra expenses yet. Add one when you need it.'; container.append(p); }
    draft.extras.forEach(extra => {
      const row = document.createElement('div'); row.className = 'budget-extra'; row.dataset.extraId = extra.id;
      const nameLabel = document.createElement('label'); nameLabel.textContent = 'Expense'; const name = document.createElement('input'); name.type = 'text'; name.maxLength = 80; name.value = extra.name; name.placeholder = 'e.g. Dinner or medicines'; name.setAttribute('aria-label', 'Extra expense name'); name.addEventListener('input', () => { extra.name = name.value; saveBudget(); }); nameLabel.append(name);
      const amountLabel = document.createElement('label'); amountLabel.textContent = 'Amount (₱)'; amountLabel.append(budgetAmountInput(extra.amount, 'Extra expense amount', value => extra.amount = value));
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'icon-button'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Remove ' + (extra.name || 'extra expense')); remove.addEventListener('click', () => { draft.extras = draft.extras.filter(e => e.id !== extra.id); saveBudget(); renderBudgetExtras(); updateBudgetTotals(); byId('budget-add-extra').focus(); }); row.append(nameLabel, amountLabel, remove); container.append(row);
    });
  }
  function renderBudget() {
    const draft = budgetDraft(), totals = budgetTotals();
    byId('budget-start').value = budgetStart; byId('budget-end').value = budgetEnd;
    byId('budget-income').value = totals.income.toFixed(2); byId('budget-carry').value = draft.carry.toFixed(2);
    renderBudgetPeriodSelection();
    const container = byId('budget-bills'); container.replaceChildren();
    const events = budgetEvents().filter(e => e.flow.direction === 'expense'), groupMap = new Map();
    events.forEach(item => { const cycle = budgetCycle(item.date); if (!groupMap.has(cycle.key)) groupMap.set(cycle.key, { cycle, items: [], lists: {}, subtotals: {} }); groupMap.get(cycle.key).items.push(item); });
    budgetGroups = [...groupMap.values()];
    container.classList.toggle('single-cycle', budgetGroups.length === 1);
    budgetGroups.forEach(group => {
      const section = document.createElement('section'); section.className = 'budget-cycle ' + group.cycle.type; section.dataset.budgetCycle = group.cycle.key;
      const header = document.createElement('div'); header.className = 'budget-cycle-header';
      const badge = document.createElement('span'); badge.className = 'budget-cycle-number'; badge.textContent = group.cycle.type === 'first' ? '1' : '2'; badge.setAttribute('aria-hidden', 'true');
      const label = document.createElement('div'), title = document.createElement('h3'), dates = document.createElement('p'); title.textContent = monthName.format(group.cycle.start) + ' · ' + group.cycle.name;
      dates.textContent = shortDate.format(group.cycle.start) + ' – ' + shortDate.format(group.cycle.end); label.append(title, dates);
      const total = document.createElement('div'); total.className = 'budget-cycle-total'; const caption = document.createElement('span'); caption.textContent = 'Included bills'; group.total = document.createElement('strong'); total.append(caption, group.total); header.append(badge, label, total); section.append(header);
      if (monthKey(group.cycle.start) < monthKey(dateFrom(budgetStart))) { const previous = document.createElement('p'); previous.className = 'budget-cycle-previous'; previous.textContent = 'From the previous month’s 25th payday'; section.append(previous); }
      ['monthly', 'once'].forEach(schedule => {
        if (!group.items.some(e => e.flow.schedule === schedule)) return;
        const sub = document.createElement('section'); sub.className = 'budget-frequency ' + (schedule === 'monthly' ? 'recurring-tone' : 'once-tone'); sub.dataset.budgetFrequency = schedule;
        const subhead = document.createElement('div'); subhead.className = 'budget-frequency-header'; const name = document.createElement('h4'); name.textContent = (schedule === 'monthly' ? 'Recurring' : 'One-time') + ' (' + group.items.filter(e => e.flow.schedule === schedule).length + ')';
        group.subtotals[schedule] = document.createElement('strong'); subhead.append(name, group.subtotals[schedule]); group.lists[schedule] = document.createElement('div'); sub.append(subhead, group.lists[schedule]); section.append(sub);
      });
      container.append(section);
    });
    events.forEach(item => {
      const key = budgetBillKey(item), edit = draft.bills[key], row = document.createElement('div'); row.className = 'budget-bill'; row.dataset.budgetBill = key;
      const icon = document.createElement('span'); icon.className = 'entry-icon'; icon.append(uiIcon(flowIcon(item.flow)));
      const check = document.createElement('input'); check.type = 'checkbox'; check.checked = !item.paid && (!edit || edit.included); check.disabled = !!item.paid; check.setAttribute('aria-label', 'Include ' + item.flow.name + ' due ' + iso(item.date));
      const label = document.createElement('div'), title = document.createElement('strong'), note = document.createElement('span'); title.textContent = displayName(item.flow); title.title = item.flow.name; note.className = 'item-meta'; note.textContent = shortDate.format(item.date) + (item.paid ? ' · Paid' : isCard(item.flow) ? ' · Card payment' : '') + (item.partial ? ' · ' + peso2.format(item.paidAmount) + ' paid' : ''); label.append(title, note);
      const amount = document.createElement('button'); amount.type = 'button'; amount.className = 'budget-row-amount'; amount.textContent = peso2.format(budgetBillAmount(item, edit)); amount.setAttribute('aria-label', 'Adjust budget for ' + item.flow.name); amount.disabled = !!item.paid;
      const input = budgetAmountInput(budgetBillAmount(item, edit), 'Budget amount for ' + item.flow.name + ' due ' + iso(item.date), value => { draft.bills[key] = { included: check.checked, amount: value, paidAtEdit: item.paidAmount || 0 }; amount.textContent = peso2.format(value); }); input.disabled = !!item.paid || !check.checked;
      row.classList.toggle('budget-excluded', !check.checked);
      check.addEventListener('change', () => { draft.bills[key] = { included: check.checked, amount: Number(input.value), paidAtEdit: item.paidAmount || 0 }; input.disabled = !check.checked; row.classList.toggle('budget-excluded', !check.checked); saveBudget(); updateBudgetTotals(); });
      const schedule = document.createElement('button'); schedule.type = 'button'; schedule.className = 'text-link budget-edit'; schedule.textContent = 'Edit schedule'; schedule.setAttribute('aria-label', 'Edit schedule for ' + item.flow.name); schedule.addEventListener('click', () => openFlow(item.flow.id));
      const actions = document.createElement('div'); actions.className = 'budget-bill-actions';
      if (!item.paid && item.amount < 0) {
        const pay = document.createElement('button'); pay.type = 'button'; pay.className = 'button button-primary pay-button'; pay.textContent = item.partial ? 'Pay rest' : 'Pay'; pay.setAttribute('aria-label', 'Record payment for ' + item.flow.name); pay.addEventListener('click', () => payOccurrence(item)); actions.append(pay);
      }
      const include = document.createElement('label'); include.className = 'budget-include'; include.append(check, document.createTextNode(item.paid ? 'Paid' : 'Include'));
      const adjustments = document.createElement('div'); adjustments.className = 'budget-adjustments'; adjustments.hidden = true;
      const caption = document.createElement('label'); caption.textContent = 'Draft amount (₱)'; caption.append(input);
      const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-button'; close.append(uiIcon('x')); close.setAttribute('aria-label', 'Close adjustments for ' + item.flow.name); close.addEventListener('click', () => { adjustments.hidden = true; amount.setAttribute('aria-expanded', 'false'); amount.focus(); });
      amount.setAttribute('aria-expanded', 'false'); amount.addEventListener('click', () => { adjustments.hidden = !adjustments.hidden; amount.setAttribute('aria-expanded', String(!adjustments.hidden)); if (!adjustments.hidden && !input.disabled) input.focus(); });
      adjustments.append(caption, include, schedule, close);
      row.append(icon, label, amount, actions, adjustments); groupMap.get(budgetCycle(item.date).key).lists[item.flow.schedule].append(row);
    });
    budgetGroups.forEach(group => {
      const list = group.lists.monthly;
      if (!list || list.children.length <= 3) return;
      const rows = [...list.children], more = document.createElement('button'); more.type = 'button'; more.className = 'text-link budget-show-more'; more.setAttribute('aria-expanded', 'false');
      const update = expanded => { rows.forEach((row, index) => row.hidden = !expanded && index >= 3); more.setAttribute('aria-expanded', String(expanded)); more.textContent = expanded ? 'Show fewer recurring bills' : 'See all ' + rows.length + ' recurring bills'; };
      more.addEventListener('click', () => update(more.getAttribute('aria-expanded') !== 'true')); update(false); list.append(more);
    });
    if (!container.children.length) { const p = document.createElement('p'); p.className = 'budget-empty'; p.textContent = 'No bills due in this period. Add a recurring bill or an extra expense below.'; container.append(p); }
    renderBudgetExtras(); updateBudgetTotals();
  }
  function setBudgetPeriod(start, end) {
    if (!isDate(start) || !isDate(end) || end < start || (dateFrom(end) - dateFrom(start)) / 86400000 > 366) { byId('budget-period-note').textContent = 'Choose an end date on or after the start, within one year.'; return; }
    budgetStart = start; budgetEnd = end; byId('budget-period-note').textContent = 'Both dates are included. Each period has its own draft.'; saveBudget(); renderBudget();
  }
  ['budget-start', 'budget-end'].forEach(id => byId(id).addEventListener('change', () => setBudgetPeriod(byId('budget-start').value, byId('budget-end').value)));
  ['prev', 'next'].forEach(direction => byId('budget-' + direction + '-month').addEventListener('click', () => {
    const current = dateFrom(budgetStart), selected = document.querySelector('[data-budget-period][aria-pressed=true]'), mode = selected ? selected.dataset.budgetPeriod : 'first';
    const y = current.getFullYear(), m = current.getMonth() + (direction === 'next' ? 1 : -1);
    setBudgetPeriod(iso(new Date(y, m, mode === 'first' ? 10 : mode === 'second' ? 25 : 1, 12)), iso(mode === 'first' ? new Date(y, m, 24, 12) : mode === 'second' ? new Date(y, m + 1, 9, 12) : new Date(y, m + 1, 0, 12)));
  }));
  byId('budget-edit-income').addEventListener('click', () => { byId('budget-income-editor').open = true; byId('budget-income').focus(); });
  document.querySelectorAll('[data-budget-period]').forEach(button => button.addEventListener('click', () => {
    const date = dateFrom(budgetStart), y = date.getFullYear(), m = date.getMonth(), mode = button.dataset.budgetPeriod;
    const start = new Date(y, m, mode === 'first' ? 10 : mode === 'second' ? 25 : 1, 12);
    const end = mode === 'first' ? new Date(y, m, 24, 12) : mode === 'second' ? new Date(y, m + 1, 9, 12) : new Date(y, m + 1, 0, 12);
    setBudgetPeriod(iso(start), iso(end));
  }));
  ['income', 'carry'].forEach(field => byId('budget-' + field).addEventListener('input', function () { if (this.value === '' || !this.validity.valid) return; budgetDraft()[field] = Number(this.value); saveBudget(); updateBudgetTotals(); }));
  byId('budget-income-reset').addEventListener('click', () => { budgetDraft().income = null; saveBudget(); renderBudget(); });
  byId('budget-add-extra').addEventListener('click', () => { budgetDraft().extras.push({ id: uniqueId('extra'), name: '', amount: 0 }); saveBudget(); renderBudgetExtras(); updateBudgetTotals(); byId('budget-extras').lastElementChild.querySelector('input').focus(); });
  byId('budget-add-recurring').addEventListener('click', () => { openFlow(); byId('flow-dialog-title').textContent = 'Add recurring bill'; byId('flow-direction').value = 'expense'; byId('flow-schedule').value = 'monthly'; byId('flow-start').value = budgetStart; byId('flow-day').value = dateFrom(budgetStart).getDate(); toggleFlowFields(); });
  byId('budget-reset').addEventListener('click', () => { if (!window.confirm('Reset income, carry-over, bill adjustments, and extra expenses in this draft? Your schedules and payment records are kept.')) return; delete state.cashPlans[budgetKey()]; saveBudget(); renderBudget(); });
  byId('budget-bottom').addEventListener('click', () => window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }));
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => { byId('budget-bottom').hidden = entries[0].isIntersecting || byId('budget').hidden; }).observe(document.querySelector('.budget-result'));
  }
  document.querySelectorAll('[data-scope]').forEach(button => button.addEventListener('click', () => { scopeMode = button.dataset.scope; renderOverview(lastForecast); }));
  byId('scope-month').addEventListener('change', function () { if (/^\d{4}-\d{2}$/.test(this.value) && isDate(this.value + '-01')) { scopeMonth = this.value; renderOverview(lastForecast); } });
  ['prev', 'next'].forEach(direction => byId('scope-' + direction).addEventListener('click', () => { const date = dateFrom(scopeMonth + '-01'); date.setMonth(date.getMonth() + (direction === 'next' ? 1 : -1)); scopeMonth = monthKey(date); renderOverview(lastForecast); }));
  byId('scope-show-month').addEventListener('click', () => { scopeMode = 'month'; renderOverview(lastForecast); document.querySelector('.scope-result').scrollIntoView({ block: 'start' }); });
  byId('scope-plan').addEventListener('click', () => { const range = scopeRange(); setBudgetPeriod(iso(range.start), iso(range.end)); location.hash = 'budget'; });
  function openPeriodIncome(range, fromBudget = false) {
    const snapshot = dateFrom(state.asOf), start = range.start > snapshot ? range.start : addDays(snapshot, 1);
    incomeEdits = buildEvents(start, range.end, state.scenario).filter(e => e.flow.direction === 'income');
    if (!incomeEdits.length) { showToast('No upcoming payday income in this range. Add an income entry or update your cash snapshot for income already received.'); return; }
    incomeEditorRange = { start: iso(range.start), end: iso(range.end) }; incomeEditorFromBudget = fromBudget;
    byId('period-income-title').textContent = incomeEdits.length === 1 ? 'Update this period’s income' : 'Update payday incomes';
    byId('period-income-description').textContent = shortDate.format(range.start) + ' – ' + shortDate.format(range.end) + '. Enter your take-home pay, including on-call earnings.';
    const entries = byId('period-income-entries'); entries.replaceChildren();
    const draft = fromBudget ? budgetDraft() : null;
    incomeEdits.forEach((item, index) => {
      const label = document.createElement('label'); label.className = 'period-pay-entry'; label.textContent = item.flow.name + ' · ' + shortDate.format(item.date);
      const input = document.createElement('input'); input.id = 'period-pay-' + index; input.type = 'number'; input.min = '0'; input.step = '0.01'; input.inputMode = 'decimal'; input.required = true;
      input.value = (draft && draft.income !== null && incomeEdits.length === 1 ? draft.income : item.skipped ? eventAmount(item.flow, state.scenario) : item.amount).toFixed(2);
      const note = document.createElement('span'); note.className = 'item-meta'; note.textContent = 'Default: ' + peso2.format(eventAmount(item.flow, state.scenario)) + ' · update only this payday'; label.append(input, note); entries.append(label);
    });
    byId('period-income-dialog').showModal(); byId('period-pay-0').focus();
  }
  function savePeriodIncome(event) {
    event.preventDefault();
    const amounts = incomeEdits.map((item, index) => Number(byId('period-pay-' + index).value));
    if (amounts.some(amount => !Number.isFinite(amount) || amount < 0)) return;
    const next = clone(state);
    incomeEdits.forEach((item, index) => { const flow = next.flows.find(f => f.id === item.flow.id); flow.overrides = flow.overrides || {}; flow.overrides[item.originalDate] = { ...(flow.overrides[item.originalDate] || {}), date: iso(item.date), amount: amounts[index], skip: false }; });
    if (incomeEditorFromBudget && next.cashPlans && next.cashPlans[incomeEditorRange.start + ':' + incomeEditorRange.end]) next.cashPlans[incomeEditorRange.start + ':' + incomeEditorRange.end].income = null;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (error) { showToast('Income was not saved. Browser storage is unavailable.'); return; }
    state = next; byId('period-income-dialog').close(); render(); showToast('Period income saved. Forecast and monthly totals updated.');
  }
  byId('scope-update-pay').addEventListener('click', () => openPeriodIncome(scopeRange()));
  byId('budget-update-pay').addEventListener('click', () => openPeriodIncome({ start: dateFrom(budgetStart), end: dateFrom(budgetEnd) }, true));
  byId('period-income-form').addEventListener('submit', savePeriodIncome);
  byId('close-period-income').addEventListener('click', () => byId('period-income-dialog').close());
  byId('reset-period-income').addEventListener('click', () => incomeEdits.forEach((item,index) => byId('period-pay-' + index).value = eventAmount(item.flow, state.scenario).toFixed(2)));
  byId('forecast-grouping').addEventListener('click', event => { const button = event.target.closest('[data-forecast-group]'); if (!button) return; forecastGrouping = button.dataset.forecastGroup; document.querySelectorAll('[data-forecast-group]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); renderTables(lastForecast); });
  window.addEventListener('hashchange', switchView);
  render(); switchView();
})();
