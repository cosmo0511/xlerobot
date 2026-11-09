const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const mm = 96/25.4;
  const p = await b.newPage({ viewport: { width: Math.round(900*mm), height: Math.round(1200*mm) } });
  await p.goto('file://' + __dirname + '/poster_a0.html');
  await p.evaluate(() => document.fonts.ready);
  const info = await p.evaluate(() => {
    const mm = 96/25.4, foot = document.querySelector('footer').getBoundingClientRect().top;
    return [...document.querySelectorAll('.col')].map(c => {
      const last = c.lastElementChild.getBoundingClientRect().bottom;
      return Math.round((foot - last)/mm) + 'mm above footer';
    });
  });
  console.log(info);
  if (process.argv[2]) await p.screenshot({ path: process.argv[2] });
  await p.pdf({ path: __dirname + '/poster_90x120.pdf', width: '900mm', height: '1200mm', printBackground: true });
  await b.close();
})();
