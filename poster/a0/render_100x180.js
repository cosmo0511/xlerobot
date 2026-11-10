// 100 x 180 cm 포스터 렌더.
// 1) 본문 배율 z 를 키워 가며 180cm 에 들어가는 최대값을 찾고
// 2) 사진 높이로 두 단 끝을 맞춘 뒤 3) 남는 높이를 섹션 간격으로 나눈다.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const mm = 96 / 25.4;
  const p = await b.newPage({ viewport: { width: Math.round(1000 * mm), height: Math.round(1800 * mm) } });
  await p.goto('file://' + __dirname + '/poster_100x180.html');
  await p.evaluate(() => document.fonts.ready);
  const info = await p.evaluate(() => {
    const mm = 96 / 25.4, st = document.documentElement.style;
    const cols = [...document.querySelectorAll('.col')], refs = document.getElementById('refs');
    const foot = () => document.querySelector('footer').getBoundingClientRect().top / mm;
    const bottom = c => c.lastElementChild.getBoundingClientRect().bottom / mm;
    const set = (z, photo, gap) => { st.setProperty('--z', z); st.setProperty('--photo', photo + 'mm');
                                     st.setProperty('--gap', gap + 'mm'); refs.style.marginTop = gap + 'mm'; };
    const balance = (z, gap) => {           // 사진 높이로 왼쪽 단 = 오른쪽 단
      let photo = 240;
      for (let i = 0; i < 4; i++) { set(z, photo, gap); photo += (bottom(cols[1]) - bottom(cols[0])) / z;
                                    photo = Math.max(150, Math.min(420, photo)); }
      set(z, photo, gap); return photo;
    };
    const LIMIT = () => foot() - 26;          // 참고문헌 아래 여유
    let best = 1;
    for (let z = 1.0; z <= 1.6001; z += 0.01) { balance(z, 12); if (refs.getBoundingClientRect().bottom / mm <= LIMIT()) best = z; else break; }
    let photo = balance(best, 12);
    const n = Math.max(cols[0].children.length, cols[1].children.length);   // 단 안 간격 + 참고문헌 위 간격
    const slack = (LIMIT() - refs.getBoundingClientRect().bottom / mm) / best;
    const gap = 12 + slack / n;
    photo = balance(best, gap);
    return { z: +best.toFixed(2), photo: Math.round(photo), gap: +gap.toFixed(1),
             left_end: Math.round(bottom(cols[0])), right_end: Math.round(bottom(cols[1])),
             refs_bottom: Math.round(refs.getBoundingClientRect().bottom / mm), footer_top: Math.round(foot()) };
  });
  console.log(info);
  if (process.argv[2]) await p.screenshot({ path: process.argv[2] });
  await p.pdf({ path: __dirname + '/poster_100x180.pdf', width: '1000mm', height: '1800mm', printBackground: true });
  await b.close();
})();
