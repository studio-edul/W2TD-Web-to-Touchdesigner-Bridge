// W2TD Stay-tion | line_glsl_split.frag
// ======================================
// GLSL TOP — 터치/비터치 채널 분리 렌더
//
// 기존 line_glsl.frag와 동일한 노드 구성으로 사용.
// uShowHighlighted 값으로 모드를 구분한다:
//   1.0 → 터치된 채널만 렌더 (hlMask==0이면 아무것도 안 그림)
//   0.0 → 터치 안 된 채널만 렌더 (hlMask==0이면 전체 그림)
//
// 배경은 투명(alpha=0)으로 출력 → Over 컴포짓 가능
//
// ── Vectors 탭 Uniform ───────────────────────────────────────
//   uLineWidth       float  선 반폭 (UV 단위)    기본값 0.002
//   uSpeedScale      float  기울기 배율           기본값 1.0
//   uShowHighlighted float  1.0=터치, 0.0=비터치  기본값 0.0

uniform float uLineWidth;
uniform float uSpeedScale;
uniform float uShowHighlighted;
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
    vec4 col = vec4(0.0, 0.0, 0.0, 0.0);  // 투명 배경

    float hw    = (uLineWidth  > 0.0) ? uLineWidth  : 0.002;
    float scale = (uSpeedScale > 0.0) ? uSpeedScale : 1.0;
    bool  showHL = (uShowHighlighted > 0.5);

#if TD_NUM_2D_INPUTS > 0
    ivec2 texSize = textureSize(sTD2DInputs[0], 0);
    int histLen  = texSize.x;
    int numSlots = texSize.y;

    // 마지막-1 row = _highlight, 마지막 row = _maxY
    int numData = numSlots - 2;

    if (numData > 0 && histLen >= 2) {
        int   hlMask  = int(texelFetch(sTD2DInputs[0], ivec2(0, numSlots - 2), 0).r);
        float dynMaxY = texelFetch(sTD2DInputs[0], ivec2(0, numSlots - 1), 0).r;
        if (dynMaxY <= 0.0) dynMaxY = 100.0;

        int i0 = clamp(int(uv.x * float(histLen)), 0, histLen - 2);
        int i1 = i0 + 1;

        float x0 = float(i0) / float(histLen);
        float x1 = float(i1) / float(histLen);

        for (int s = 0; s < numData; s++) {
            // 채널 포함 여부 결정
            bool isHL = (hlMask > 0) && ((hlMask & (1 << s)) != 0);

            // hlMask==0 (터치 없음): showHL=false 쪽(비터치)이 전체 담당
            if (hlMask == 0 && showHL) continue;
            if (hlMask >  0 && showHL  && !isHL) continue;
            if (hlMask >  0 && !showHL &&  isHL) continue;

            float y0 = texelFetch(sTD2DInputs[0], ivec2(i0, s), 0).r;
            float y1 = texelFetch(sTD2DInputs[0], ivec2(i1, s), 0).r;

            if (y0 < -0.5 || y1 < -0.5) continue;

            float uy0 = 1.0 - clamp(y0 * scale / dynMaxY, 0.0, 1.0);
            float uy1 = 1.0 - clamp(y1 * scale / dynMaxY, 0.0, 1.0);

            vec2 a = vec2(x0, uy0);
            vec2 b = vec2(x1, uy1);

            vec4  c    = (uLineColor.a > 0.0) ? uLineColor : vec4(PALETTE[s % 20], 1.0);
            float mask = lineMask(uv, a, b, hw);
            col = mix(col, vec4(c.rgb, 1.0), mask);
        }
    }
#endif

    fragColor = TDOutputSwizzle(col);
}
