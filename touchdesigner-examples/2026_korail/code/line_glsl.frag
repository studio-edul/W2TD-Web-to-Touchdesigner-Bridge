// W2TD Stay-tion | line_glsl.frag
// =================================
// GLSL TOP 프래그먼트 쉐이더 — 철도 다이어그램
//
// ── 필요한 TD 노드 구성 ──────────────────────────────────────
//   line_chop (Script CHOP)
//       ↓
//   [CHOP to TOP]   ← 이 노드 추가 필요
//       ↓ Input 0
//   [GLSL TOP]   ← Feedback 연결 불필요
//
// ── 텍스처 레이아웃 (CHOP to TOP 출력) ───────────────────────
//   width  = HISTORY_LEN (샘플 수)
//   height = 활성 슬롯 수
//   texelFetch(sTD2DInputs[0], ivec2(sampleIdx, slotRow), 0).r
//            = slotRow번째 슬롯의 sampleIdx번째 y값
//
// ── Vectors 탭 Uniform ───────────────────────────────────────
//   uLineWidth    float  선 반폭 (UV 단위)    기본값 0.002
//   uSpeedScale   float  기울기 배율           기본값 1.0
//   uLineOpacity  float  비하이라이트 선 투명도 기본값 0.5

uniform float uLineWidth;
uniform float uSpeedScale;
uniform float uLineOpacity;
uniform vec4  uLineColor;

// 슬롯 색상 팔레트 (슬롯 행 순서대로 적용)
const vec3 PALETTE[20] = vec3[20](
    vec3(0.40, 0.80, 1.00),
    vec3(1.00, 0.40, 0.40),
    vec3(0.40, 1.00, 0.40),
    vec3(1.00, 1.00, 0.40),
    vec3(1.00, 0.40, 1.00),
    vec3(0.40, 1.00, 1.00),
    vec3(1.00, 0.80, 0.40),
    vec3(0.80, 0.40, 1.00),
    vec3(0.40, 0.80, 0.40),
    vec3(1.00, 0.60, 0.80),
    vec3(0.60, 0.80, 1.00),
    vec3(1.00, 0.60, 0.40),
    vec3(0.60, 1.00, 0.80),
    vec3(1.00, 0.80, 1.00),
    vec3(0.80, 1.00, 0.40),
    vec3(0.40, 0.60, 1.00),
    vec3(1.00, 0.40, 0.60),
    vec3(0.40, 1.00, 0.60),
    vec3(0.80, 0.60, 0.40),
    vec3(0.60, 0.40, 1.00)
);

// ── 선분 SDF ─────────────────────────────────────────────────

float sdSegment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float len2 = dot(ba, ba);
    if (len2 < 1e-12) return length(pa);
    float t = clamp(dot(pa, ba) / len2, 0.0, 1.0);
    return length(pa - ba * t);
}

float lineMask(vec2 uv, vec2 a, vec2 b, float hw) {
    float d = sdSegment(uv, a, b);
    return 1.0 - smoothstep(hw, hw * 2.0, d);
}

// ── Main ─────────────────────────────────────────────────────

out vec4 fragColor;

void main() {
    vec2 uv = vUV.st;
    vec4 col = vec4(0.0, 0.0, 0.0, 1.0);

    float hw       = (uLineWidth   > 0.0) ? uLineWidth   : 0.002;
    float scale    = (uSpeedScale  > 0.0) ? uSpeedScale  : 1.0;
    float dimAlpha = (uLineOpacity > 0.0) ? uLineOpacity : 0.5;

#if TD_NUM_2D_INPUTS > 0
    ivec2 texSize = textureSize(sTD2DInputs[0], 0);
    int histLen  = texSize.x;
    int numSlots = texSize.y;

    // 마지막-1 row = _highlight, 마지막 row = _maxY (line_chop 출력)
    int numData = numSlots - 2;

    if (numData > 0 && histLen >= 2) {
        // 하이라이트 비트마스크 읽기 (0 = 하이라이트 없음)
        int hlMask  = int(texelFetch(sTD2DInputs[0], ivec2(0, numSlots - 2), 0).r);

        // dynMaxY 읽기
        float dynMaxY = texelFetch(sTD2DInputs[0], ivec2(0, numSlots - 1), 0).r;
        if (dynMaxY <= 0.0) dynMaxY = 100.0;

        // 오른쪽이 현재(최신), 왼쪽이 과거
        int i0 = clamp(int(uv.x * float(histLen)), 0, histLen - 2);
        int i1 = i0 + 1;

        float x0 = float(i0) / float(histLen);
        float x1 = float(i1) / float(histLen);

        for (int s = 0; s < numData; s++) {
            float y0 = texelFetch(sTD2DInputs[0], ivec2(i0, s), 0).r;
            float y1 = texelFetch(sTD2DInputs[0], ivec2(i1, s), 0).r;

            // NO_DATA 구간 스킵
            if (y0 < -0.5 || y1 < -0.5) continue;

            // y축: 위가 0, 아래로 갈수록 값 증가 (상하반전)
            float uy0 = 1.0 - clamp(y0 * scale / dynMaxY, 0.0, 1.0);
            float uy1 = 1.0 - clamp(y1 * scale / dynMaxY, 0.0, 1.0);

            vec2 a = vec2(x0, uy0);
            vec2 b = vec2(x1, uy1);

            vec4  c     = (uLineColor.a > 0.0) ? uLineColor : vec4(PALETTE[s % 20], 1.0);
            // hlMask==0: 터치 없음 → 전체 풀 opacity
            // hlMask>0 : 해당 bit 켜진 채널만 풀 opacity, 나머지 dim
            bool  lit   = (hlMask == 0) || ((hlMask & (1 << s)) != 0);
            float alpha = lit ? 1.0 : dimAlpha;
            float mask  = lineMask(uv, a, b, hw);
            col = mix(col, vec4(c.rgb, alpha), mask * alpha);
        }
    }
#endif

    fragColor = TDOutputSwizzle(col);
}
