/* Prints the GPU a Windows program sees through D3D9 and DXGI: vendor, device,
 * name, video memory and driver version, one line per API. Built with
 * llvm-mingw by check-gpu-identity.sh. */
#define COBJMACROS
#include <windows.h>
#include <initguid.h>
#include <d3d9.h>
#include <d3d10.h>
#include <dxgi.h>
#include <stdio.h>

static void print_version(LARGE_INTEGER v)
{
    printf("%u.%u.%u.%u", HIWORD(v.HighPart), LOWORD(v.HighPart), HIWORD(v.LowPart), LOWORD(v.LowPart));
}

int main(void)
{
    D3DADAPTER_IDENTIFIER9 id9;
    DXGI_ADAPTER_DESC desc;
    IDXGIFactory *factory;
    IDXGIAdapter *adapter;
    IDirect3D9 *d3d9;
    LARGE_INTEGER umd;
    int failed = 0;

    if ((d3d9 = Direct3DCreate9(D3D_SDK_VERSION)) && SUCCEEDED(IDirect3D9_GetAdapterIdentifier(d3d9, 0, 0, &id9)))
    {
        printf("d3d9 %04lx:%04lx ", id9.VendorId, id9.DeviceId);
        print_version(id9.DriverVersion);
        printf(" %s\n", id9.Description);
    }
    else
    {
        printf("d3d9 failed\n");
        failed = 1;
    }
    if (d3d9) IDirect3D9_Release(d3d9);

    if (SUCCEEDED(CreateDXGIFactory(&IID_IDXGIFactory, (void **)&factory))
            && SUCCEEDED(IDXGIFactory_EnumAdapters(factory, 0, &adapter)))
    {
        IDXGIAdapter_GetDesc(adapter, &desc);
        printf("dxgi %04x:%04x ", desc.VendorId, desc.DeviceId);
        if (SUCCEEDED(IDXGIAdapter_CheckInterfaceSupport(adapter, &IID_ID3D10Device, &umd)))
            print_version(umd);
        else
            printf("unsupported");
        printf(" %lluMB %ls\n", (unsigned long long)desc.DedicatedVideoMemory >> 20, desc.Description);
        IDXGIAdapter_Release(adapter);
        IDXGIFactory_Release(factory);
    }
    else
    {
        printf("dxgi failed\n");
        failed = 1;
    }
    return failed;
}
