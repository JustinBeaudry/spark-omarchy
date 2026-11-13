/* Experimental Wine compatibility shim, not a system replacement.
 * Foundation imports GetAllUsersProfileDirectoryW; Wine 11.20 stubs it.
 * Use the existing Wine common-appdata known folder, preserving buffer rules.
 */
#include <windows.h>
#include <shlobj.h>

BOOL WINAPI spark_GetAllUsersProfileDirectoryW(LPWSTR buffer, LPDWORD size)
{
    WCHAR path[MAX_PATH];
    DWORD required;
    HRESULT hr;
    if (!size) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    hr = SHGetFolderPathW(NULL, CSIDL_COMMON_APPDATA, NULL, SHGFP_TYPE_CURRENT, path);
    if (FAILED(hr)) {
        SetLastError(HRESULT_FACILITY(hr) == FACILITY_WIN32 ? HRESULT_CODE(hr) : ERROR_PATH_NOT_FOUND);
        return FALSE;
    }
    required = lstrlenW(path) + 1;
    if (!buffer || *size < required) {
        *size = required;
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return FALSE;
    }
    lstrcpyW(buffer, path);
    *size = required;
    return TRUE;
}
