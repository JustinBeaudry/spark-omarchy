#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

typedef BOOL (WINAPI *profile_fn)(LPWSTR, LPDWORD);
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s (error %lu)\n", __LINE__, #x, (unsigned long)GetLastError()); return 1; } } while (0)

int main(void)
{
    HMODULE mod = LoadLibraryW(L"spkenv.dll");
    profile_fn fn, forwarded;
    union { FARPROC generic; profile_fn profile; } address;
    WCHAR buffer[MAX_PATH];
    DWORD size = 0, required;
    CHECK(mod != NULL);
    address.generic = GetProcAddress(mod, "GetAllUsersProfileDirectoryW");
    fn = address.profile;
    address.generic = GetProcAddress(mod, "GetProfilesDirectoryW");
    forwarded = address.profile;
    CHECK(fn && forwarded);
    CHECK(!fn(NULL, NULL));
    CHECK(GetLastError() == ERROR_INVALID_PARAMETER);
    CHECK(!fn(NULL, &size));
    CHECK(GetLastError() == ERROR_INSUFFICIENT_BUFFER && size > 1 && size <= MAX_PATH);
    required = size;
    buffer[0] = 0x1234;
    size = required - 1;
    CHECK(!fn(buffer, &size));
    CHECK(GetLastError() == ERROR_INSUFFICIENT_BUFFER && size == required && buffer[0] == 0x1234);
    size = required;
    CHECK(fn(buffer, &size));
    CHECK(size == required && (DWORD)lstrlenW(buffer) + 1 == required);
    size = MAX_PATH;
    CHECK(forwarded(buffer, &size));
    puts("PASS: null arguments, size query, short buffer, exact buffer, USERENV forwarding");
    FreeLibrary(mod);
    return 0;
}
