# AniZen WebDAV 확장

AniZen에서 사용할 수 있는 개인 WebDAV 확장 배포 저장소입니다.

- 확장 프로그램: WebDAV
- 패키지: `eu.kanade.tachiyomi.animeextension.ko.webdav`
- 언어/국가 카테고리: `ko` (한국어)
- Extensions-lib 기준 버전: v16
- 기본 WebDAV 포트: `8081`
- 인스턴스: 서로 독립적인 WebDAV 소스 1~10개 (기본값 3개)
- 빌드 환경: `salmanbappi/sb-extensions-source`의 커밋 `c8d9cef922353b0399ee802d5a594d1884c9be41` 고정 사용

**언어:** 한국어 | [English](README.en.md)

## AniZen 저장소 주소

최초 서명 빌드가 성공한 후 다음 주소를 AniZen에 추가하세요.

```text
https://raw.githubusercontent.com/rule34kr/anizen-extensions/main/repo.json
```

AniZen에서 **설정 → 둘러보기 → 확장 프로그램 저장소 → 저장소 추가**로 이동합니다.

> 서명에 필요한 GitHub Secrets가 모두 설정되고 GitHub Actions 워크플로가 성공하기 전까지 APK와 저장소 인덱스는 게시되지 않습니다.

## 릴리스 서명 설정

신뢰할 수 있는 PC에서 JDK의 keytool을 사용해 지속적으로 사용할 서명 키를 생성합니다.

```powershell
keytool -genkeypair -v -keystore .\\webdav-signing.jks -storetype JKS -alias webdav -keyalg RSA -keysize 2048 -validity 10000
```

JKS 파일과 비밀번호는 안전하게 보관하고 저장소에 커밋하지 마세요. 이후 모든 업데이트에도 반드시 동일한 키를 사용해야 합니다.

인증서의 SHA-256 지문을 확인합니다.

```powershell
keytool -list -v -keystore .\\webdav-signing.jks -alias webdav
```

SHA256 값을 콜론과 공백 없이 소문자로 변환합니다. 결과는 정확히 64자리 16진수여야 합니다.

키스토어를 Base64로 인코딩합니다.

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\\webdav-signing.jks)))
```

**GitHub → Settings → Secrets and variables → Actions**에서 다음 저장소 Secrets를 추가합니다.

| Secret | 값 |
|---|---|
| `SIGNING_KEY` | JKS 전체 Base64 출력 |
| `ALIAS` | `webdav` |
| `KEY_STORE_PASSWORD` | 키스토어 비밀번호 |
| `KEY_PASSWORD` | 키 비밀번호 |
| `SIGNING_KEY_FINGERPRINT` | 콜론이 없는 소문자 SHA-256 지문 64자리 |

이 값들을 채팅으로 보내거나 소스 코드에 포함하지 마세요.

## 빌드 및 배포

5개 Secrets를 모두 추가한 다음 **Actions → Build and publish WebDAV extension → Run workflow**에서 `main` 브랜치의 워크플로를 실행합니다.

워크플로는 WebDAV 소스 모듈을 복원하고, Java 17/Gradle로 서명된 Release APK를 빌드하며, APK 서명 인증서를 검증합니다. 이후 AniZen Protobuf v2 저장소 인덱스와 레거시 JSON 인덱스를 생성하고 APK 및 메타데이터를 이 저장소에 게시합니다.

확장 프로그램 및 각 WebDAV 소스의 언어 코드는 모두 `ko`로 설정됩니다. WebDAV 기본 포트는 `8081`이며 HTTP 주소에 포트가 생략된 경우에도 `8081`을 사용합니다. 최대 10개의 독립적인 소스 인스턴스를 지원하며 기본값은 3개입니다. 각 인스턴스에 별도의 표시 이름을 지정할 수 있고, 연결 테스트는 실제 탐색에 사용하는 OkHttp WebDAV 요청으로 수행합니다. 기존 기본값인 `http://192.168.0.10:8080`만 자동으로 마이그레이션하며, 사용자가 직접 지정한 다른 포트는 유지합니다.

`payload/` 변경 시에도 빌드가 실행됩니다. 업데이트를 게시하기 전에는 내장 모듈의 `src/ko/webdav/build.gradle`에 있는 `extVersionCode`를 증가시켜야 합니다. 초기 소스 버전은 `16.1`입니다.

## 검증 상태

소스는 업로드된 AniZen 및 확장 소스 스냅샷을 기준으로 준비되었습니다. 호스팅 Gradle 빌드가 실제 컴파일 및 서명을 검증하는 첫 단계이며, 확장 프로그램 로딩, WebDAV PROPFIND, MPV Range 요청 및 탐색은 기기에서 별도로 확인해야 합니다.

## 보안

외부 네트워크에서 접속할 때는 HTTPS 또는 Tailscale 사용을 권장합니다. 인증되지 않은 WebDAV 서버를 공용 인터넷에 직접 노출하지 마세요. 업데이트 간 서명 키를 변경하지 마세요.
