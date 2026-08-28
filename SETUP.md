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

갱신을 **시작하는 곳**은 `CalendarGrid.initState` 입니다 — 앱 시작이 아니라 **달력이 열릴 때**.
확인 주기는 `HolidayUpdateService.checkInterval`(7일), 새 버전이면 묻지 않고 바로 적용합니다.

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

1. 앱 설치 후 **내역 → 달력**으로 이동 (여기서 갱신이 시작됩니다)
2. 달력이 **즉시** 그려지는지 확인 — 네트워크를 기다려 멈추면 안 됩니다
3. 잠시 뒤 새 공휴일이 **저절로** 빨갛게 바뀌는지 확인 (버튼을 누르지 않습니다)
4. **내역 → 달력**으로 이동해 추가한 날짜가 빨갛게 칠해졌는지 확인
4. 비행기 모드로 바꿔 앱을 재시작 → 그 날짜가 **여전히 빨간지** 확인 (캐시 동작)
5. 비행기 모드인 채로 달력을 여러 번 열어 → 멈춤·오류 없이 그대로 그려지는지 확인

### 좋은 시험 날짜

**2026년 7월 17일(제헌절)** 이 확실합니다. 18년 만에 공휴일로 재지정됐는데
앱 내장 데이터(2026-06 수집)에는 없고 이 저장소에만 있습니다.
달력을 2026년 7월로 넘겨 17일이 빨간지 보면 전 경로가 한 번에 확인됩니다.

### 7일을 기다리기 싫다면

달력 진입 시 확인에는 7일 throttle이 걸려 있지만, **설정 → 공휴일 데이터 → [지금 확인]**
버튼은 throttle을 무시하고 즉시 접속합니다. 검증은 이 버튼으로 하세요.
앱을 지웠다 다시 깔아도 됩니다(캐시가 사라져 처음부터 다시 확인합니다).

---

## 5. 개인정보처리방침

이 기능은 앱이 외부 주소에 접속하게 만듭니다. 방침에 한 줄이 필요합니다.

> 달력 화면에서 공휴일 데이터 업데이트 확인을 위해 7일에 한 번 GitHub에
> 읽기 전용으로 접속합니다. 이때 개인정보나 거래 내역은 전송되지 않습니다.

---

## 되돌리기

| 목적 | 방법 |
|---|---|
| 업데이트 기능만 끄기 | `manifestUrl = ''` 로 되돌리고 재배포. 이미 받은 날짜는 기기에 남음 |
| 저장소까지 정리 | 위를 배포해 충분히 퍼진 뒤 저장소 삭제 (순서 반대로 하면 구버전 앱이 달력 열 때마다 404를 때림 — 해는 없지만 무의미한 접속) |
| 특정 날짜만 취소 | `dates`에서 빼고 `version` +1. **단 앱 내장 날짜는 이 방법으로 못 지움**(앱 업데이트 필요) |

---

## 데이터 갱신 담당자를 위한 체크리스트

- [ ] 공식 발표를 확인했는가 (관보 / 한국천문연구원 특일정보)
- [ ] 고정 양력 8종이 아닌가 (그건 앱이 계산하므로 넣지 않음)
- [ ] `YYYY-MM-DD` 형식인가 (`2026-8-17` 같은 표기는 조용히 버려짐)
- [ ] **`version`을 +1 했는가** ← 가장 자주 빠뜨림
- [ ] JSON이 유효한가 (`python -m json.tool holidays.json`, push하면 CI도 검사)
