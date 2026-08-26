# SETUP — 앱에 연결하기

`holidays.json`을 호스팅하는 것만으로는 아무 일도 일어나지 않습니다.
앱이 이 URL을 알아야 합니다. 상수 한 줄입니다.

---

## 1. URL 확인

```
https://raw.githubusercontent.com/gilomonlabs/check_holidays/main/holidays.json
```

브라우저나 `curl`로 열어 JSON이 그대로 보이면 준비 끝입니다.

```bash
curl -s https://raw.githubusercontent.com/gilomonlabs/check_holidays/main/holidays.json | head -5
```

> 저장소가 **Public**이어야 합니다. Private이면 raw URL에 토큰이 필요해지고,
> 그 토큰이 앱 바이너리에 박히게 됩니다 — 하면 안 됩니다.

---

## 2. 앱 상수 교체

모니모아 저장소의 `lib/services/holiday_update_service.dart`:

```dart
// 전
static const String manifestUrl = '';

// 후
static const String manifestUrl =
    'https://raw.githubusercontent.com/gilomonlabs/check_holidays/main/holidays.json';
```

빈 문자열이면 앱은 업데이트 확인 자체를 건너뜁니다(완전 오프라인 동작). 되돌릴 때도 이 값을 비우면 됩니다.

---

## 3. 빌드 & 확인

```bash
flutter test                 # 공휴일 파싱 단위 테스트 포함
flutter build apk --release
```

### ★ 릴리스 빌드에서 반드시 확인할 것 — INTERNET 권한

Flutter는 `android.permission.INTERNET`을 **debug/profile 매니페스트에만** 자동으로 넣습니다.
`android/app/src/main/AndroidManifest.xml`에 직접 없으면 **릴리스 빌드에서 모든 네트워크가 막힙니다**
(공휴일 업데이트뿐 아니라 클라우드 백업까지). 과거에 실제로 겪은 문제입니다.

```xml
<uses-permission android:name="android.permission.INTERNET"/>
```

---

## 4. 실기기 검증

1. 앱 설치 후 실행 → **설정 → 공휴일 데이터 → [업데이트 확인]**
2. 서버 `version`이 앱의 적용 버전보다 크면 → 배너 + 설정 탭에 **빨강 점 ●**
3. **[적용]** → "버전 N · 추가 M일" 표시, 점 사라짐
4. **내역 → 달력**으로 이동해 추가한 날짜가 빨갛게 칠해졌는지 확인
5. 비행기 모드로 바꿔 앱을 재시작 → 그 날짜가 **여전히 빨간지** 확인 (캐시 동작)

### 처음이라 버전이 같아서 점이 안 뜬다면

앱의 적용 버전이 0이고 서버가 1이면 점이 뜹니다. 이미 1을 적용한 뒤 다시 시험하려면
`version`을 2로 올리고 아무 날짜나 하나 추가해 push하세요. **시험이 끝나면 되돌리고 version을 또 +1** 하세요
(내리면 무시되므로 반드시 올려야 합니다).

### 12시간을 기다리기 싫다면

시작 시 자동 확인은 12시간 throttle이 걸려 있지만, **설정의 [업데이트 확인] 버튼은 throttle을 무시**하고
즉시 접속합니다. 검증은 이 버튼으로 하세요.

---

## 5. 개인정보처리방침

이 기능은 앱이 외부 주소에 접속하게 만듭니다. 방침에 한 줄이 필요합니다.

> 공휴일 데이터 업데이트 확인을 위해 GitHub에 읽기 전용으로 접속합니다.
> 이때 개인정보나 거래 내역은 전송되지 않습니다.

---

## 되돌리기

| 목적 | 방법 |
|---|---|
| 업데이트 기능만 끄기 | `manifestUrl = ''` 로 되돌리고 재배포. 이미 적용된 날짜는 기기에 남음 |
| 저장소까지 정리 | 위를 배포해 충분히 퍼진 뒤 저장소 삭제 (순서 반대로 하면 구버전 앱이 12시간마다 404를 때림 — 해는 없지만 무의미한 접속) |
| 특정 날짜만 취소 | `dates`에서 빼고 `version` +1. **단 앱 내장 날짜는 이 방법으로 못 지움**(앱 업데이트 필요) |

---

## 데이터 갱신 담당자를 위한 체크리스트

- [ ] 공식 발표를 확인했는가 (관보 / 한국천문연구원 특일정보)
- [ ] 고정 양력 8종이 아닌가 (그건 앱이 계산하므로 넣지 않음)
- [ ] `YYYY-MM-DD` 형식인가 (`2026-8-17` 같은 표기는 조용히 버려짐)
- [ ] **`version`을 +1 했는가** ← 가장 자주 빠뜨림
- [ ] JSON이 유효한가 (`python -m json.tool holidays.json`, push하면 CI도 검사)
