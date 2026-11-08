// One-shot hardware D3D12 flip-model benchmark; never inspects a game process.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <d2d1.h>
#include <dwrite.h>
#include <wincodec.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using Microsoft::WRL::ComPtr;
using Clock = std::chrono::steady_clock;
constexpr int ColorTolerance = 12;
constexpr int CountdownSeconds = 5;
constexpr int NoticeRows = 5;
int countdown_seconds(Clock::duration elapsed) {
    auto seconds = std::chrono::duration_cast<std::chrono::seconds>(elapsed).count();
    return static_cast<int>(std::clamp<long long>(CountdownSeconds - seconds, 0, CountdownSeconds));
}
using Color = std::array<int, 3>;
constexpr Color MoonA{52, 86, 98}, MoonB{94, 70, 92};
static_assert(MoonB[0] - MoonA[0] > 2 * ColorTolerance, "Marker states must remain distinguishable");
struct Patch { D3D12_RECT rect; Color color; bool moon = false; };
// A quiet night landscape. Only the small moon changes; the rest stays still.
std::vector<Patch> make_scene(int width, int height) {
    std::vector<Patch> scene;
    for (int i = 0; i < 90; ++i)
        scene.push_back({{0, i * height / 90, width, (i + 1) * height / 90},
                         {16 + i / 9, 23 + i / 6, 34 + i / 5}});
    int cx = width * 72 / 100, cy = height * 24 / 100;
    int radius = std::min(width, height) * 6 / 100;
    for (int dy = -radius; dy < radius; ++dy) {
        int half = static_cast<int>(std::sqrt(double(radius * radius - dy * dy)));
        scene.push_back({{cx - half, cy + dy, cx + half, cy + dy + 1}, MoonA, true});
    }
    const std::array<Color, 3> hills = {{{28, 39, 51}, {31, 47, 58}, {36, 56, 63}}};
    for (int layer = 0; layer < 3; ++layer) for (int i = 0; i < 180; ++i) {
        double x = (i + .5) / 180;
        int top = static_cast<int>(height * (.58 + layer * .13 +
            .075 * std::sin(x * 7 + layer * 2) + .025 * std::sin(x * 17 + layer)));
        scene.push_back({{i * width / 180, top, (i + 1) * width / 180, height}, hills[layer]});
    }
    return scene;
}
Color moon_color(double blend) {
    Color color{};
    for (int c = 0; c < 3; ++c)
        color[c] = static_cast<int>(std::round(MoonA[c] + (MoonB[c] - MoonA[c]) * blend));
    return color;
}
Color scene_color(const std::vector<Patch>& scene, int x, int y, int phase) {
    for (auto p = scene.rbegin(); p != scene.rend(); ++p)
        if (x >= p->rect.left && x < p->rect.right && y >= p->rect.top && y < p->rect.bottom)
            return p->moon ? moon_color(phase % 2) : p->color;
    throw std::runtime_error("Scene has an uncovered pixel");
}
void check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        std::ostringstream message;
        message << operation << " failed: 0x" << std::hex << static_cast<unsigned long>(hr);
        throw std::runtime_error(message.str());
    }
}
struct NoticeLayout {
    int x, y, width, height;
    float font_size;
};
NoticeLayout notice_layout(int width, int height) {
    int box_width = std::min(740, width * 62 / 100);
    float font = std::min(24.f, (box_width - 24) / 24.f);
    return {std::max(8, width / 80), std::max(8, height / 60), box_width,
            static_cast<int>(std::ceil(font * 1.6f * NoticeRows)) + 24, font};
}
struct ComApartment {
    ComApartment() { check(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED), "CoInitializeEx"); }
    ~ComApartment() { CoUninitialize(); }
};
std::vector<unsigned char> raster_notice(const NoticeLayout& layout, int remaining) {
    // Rasterize once on the CPU with DirectWrite's CJK font fallback, then copy the
    // opaque notice into the D3D12 swap chain. No extra window or desktop overlay.
    ComApartment apartment;
    ComPtr<IWICImagingFactory> wic;
    check(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
          IID_PPV_ARGS(&wic)), "CreateWicFactory");
    ComPtr<IWICBitmap> bitmap;
    check(wic->CreateBitmap(layout.width, layout.height, GUID_WICPixelFormat32bppPBGRA,
          WICBitmapCacheOnLoad, &bitmap), "CreateNoticeBitmap");
    ComPtr<ID2D1Factory> d2d;
    check(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, d2d.GetAddressOf()), "CreateD2DFactory");
    ComPtr<ID2D1RenderTarget> target;
    auto properties = D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_SOFTWARE,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
    check(d2d->CreateWicBitmapRenderTarget(bitmap.Get(), properties, &target), "CreateNoticeTarget");
    ComPtr<IDWriteFactory> write;
    check(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
          reinterpret_cast<IUnknown**>(write.GetAddressOf())), "CreateDWriteFactory");
    ComPtr<ID2D1SolidColorBrush> brush;
    check(target->CreateSolidColorBrush(D2D1::ColorF(126 / 255.f, 143 / 255.f, 157 / 255.f), &brush), "CreateNoticeBrush");
    auto countdown = std::to_wstring(remaining) + L"...";
    const std::array<const wchar_t*, NoticeRows> lines = {
        L"自动测试截图中，请稍后", L"自動測試截圖中，請稍候",
        L"Testing screen capture, please wait",
        L"撮影方法を自動テスト中です。お待ちください", countdown.c_str()};
    const std::array<const wchar_t*, NoticeRows> locales = {L"zh-CN", L"zh-TW", L"en-US", L"ja-JP", L"en-US"};
    target->BeginDraw();
    target->Clear(D2D1::ColorF(16 / 255.f, 23 / 255.f, 34 / 255.f));
    target->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
    for (size_t row = 0; row < lines.size(); ++row) {
        ComPtr<IDWriteTextFormat> format;
        check(write->CreateTextFormat(L"Segoe UI", nullptr, DWRITE_FONT_WEIGHT_NORMAL,
              DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, layout.font_size,
              locales[row], &format), "CreateNoticeTextFormat");
        check(format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP), "SetNoticeWrapping");
        float top = 12 + static_cast<float>(row) * layout.font_size * 1.6f;
        auto rect = D2D1::RectF(12, top, static_cast<float>(layout.width - 12), top + layout.font_size * 1.6f);
        target->DrawText(lines[row], static_cast<UINT32>(wcslen(lines[row])), format.Get(), rect,
                         brush.Get(), D2D1_DRAW_TEXT_OPTIONS_CLIP);
    }
    check(target->EndDraw(), "RenderNoticeText");
    UINT pitch = layout.width * 4;
    std::vector<unsigned char> pixels(pitch * layout.height);
    check(bitmap->CopyPixels(nullptr, pitch, static_cast<UINT>(pixels.size()), pixels.data()), "CopyNoticePixels");
    for (size_t i = 0; i < pixels.size(); i += 4) std::swap(pixels[i], pixels[i + 2]); // BGRA -> RGBA.
    return pixels;
}
std::string quoted(const std::string& text) {
    std::string result = "\"";
    for (unsigned char c : text) {
        if (c == '\\' || c == '"') result += '\\';
        if (c >= 32) result += static_cast<char>(c);
    }
    return result + "\"";
}
struct Options {
    std::filesystem::path dll, report;
    int x = 0, y = 0, width = 1280, height = 720;
};
struct Result {
    std::string mode, error;
    bool valid = false;
    std::vector<double> samples;
    double error_max = 0;
};
void report(const Options& o, const std::vector<Result>& results, bool complete,
            const std::string& error = "") {
    auto temporary = o.report; temporary += L".tmp";
    std::ofstream out(temporary, std::ios::trunc);
    if (!out) throw std::runtime_error("Cannot write benchmark report");
    out << "{\"version\":1,\"renderer\":\"D3D12/flip-discard\",\"complete\":"
        << (complete ? "true" : "false") << ",\"width\":" << o.width << ",\"height\":" << o.height
        << ",\"error\":" << quoted(error) << ",\"results\":[";
    bool first = true;
    for (const auto& r : results) {
        if (!first) out << ',';
        first = false;
        out << "{\"mode\":" << quoted(r.mode) << ",\"valid\":" << (r.valid ? "true" : "false")
            << ",\"error\":" << quoted(r.error) << ",\"max_color_error\":" << r.error_max
            << ",\"samples_ms\":[";
        for (size_t i = 0; i < r.samples.size(); ++i) {
            if (i) out << ',';
            out << std::fixed << std::setprecision(4) << r.samples[i];
        }
        out << "]}";
    }
    out << "]}"; out.close();
    if (!out || !MoveFileExW(temporary.c_str(), o.report.c_str(), MOVEFILE_REPLACE_EXISTING))
        throw std::runtime_error("Cannot commit benchmark report");
}
struct Renderer {
    std::vector<Patch> scene;
    NoticeLayout notice{};
    ComPtr<ID3D12Resource> notice_upload;
    UINT notice_pitch = 0;
    UINT64 notice_frame_bytes = 0;
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<IDXGISwapChain3> swap;
    ComPtr<ID3D12DescriptorHeap> heap;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> commands;
    ComPtr<ID3D12Fence> fence;
    std::array<ComPtr<ID3D12Resource>, 2> buffers;
    HANDLE event = nullptr;
    UINT stride = 0;
    UINT64 serial = 0;
    ~Renderer() { if (event) CloseHandle(event); }
    void initialize(HWND window, int width, int height) {
        scene = make_scene(width, height);
        notice = notice_layout(width, height);
        ComPtr<IDXGIFactory4> factory;
        check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "CreateDXGIFactory1");
        ComPtr<IDXGIAdapter1> adapter;
        auto monitor = MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST);
        // Select the hardware adapter driving this monitor, including multi-GPU systems.
        for (UINT i = 0; ; ++i) {
            ComPtr<IDXGIAdapter1> candidate;
            if (factory->EnumAdapters1(i, &candidate) == DXGI_ERROR_NOT_FOUND) break;
            for (UINT j = 0; ; ++j) {
                ComPtr<IDXGIOutput> output;
                if (candidate->EnumOutputs(j, &output) == DXGI_ERROR_NOT_FOUND) break;
                DXGI_OUTPUT_DESC desc{};
                check(output->GetDesc(&desc), "GetOutputDesc");
                if (desc.Monitor == monitor) { adapter = candidate; break; }
            }
            if (adapter) break;
        }
        check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "D3D12CreateDevice");
        notice_pitch = (notice.width * 4 + D3D12_TEXTURE_DATA_PITCH_ALIGNMENT - 1) & ~(D3D12_TEXTURE_DATA_PITCH_ALIGNMENT - 1);
        notice_frame_bytes = (UINT64(notice_pitch) * notice.height + D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT - 1)
            & ~UINT64(D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT - 1);
        D3D12_HEAP_PROPERTIES upload_heap{}; upload_heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        D3D12_RESOURCE_DESC upload_desc{}; upload_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        upload_desc.Width = notice_frame_bytes * (CountdownSeconds + 1); upload_desc.Height = 1;
        upload_desc.DepthOrArraySize = 1; upload_desc.MipLevels = 1;
        upload_desc.SampleDesc.Count = 1; upload_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        check(device->CreateCommittedResource(&upload_heap, D3D12_HEAP_FLAG_NONE, &upload_desc,
              D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&notice_upload)), "CreateNoticeUpload");
        void* mapped = nullptr; D3D12_RANGE no_read{0, 0};
        check(notice_upload->Map(0, &no_read, &mapped), "MapNoticeUpload");
        // Pre-render every digit before showing the window. The benchmark only selects
        // immutable, correctly aligned upload regions, with no font work or GPU write races.
        for (int remaining = CountdownSeconds; remaining >= 0; --remaining) {
            auto pixels = raster_notice(notice, remaining);
            auto frame = static_cast<unsigned char*>(mapped) + (CountdownSeconds - remaining) * notice_frame_bytes;
            for (int row = 0; row < notice.height; ++row)
                std::memcpy(frame + row * notice_pitch,
                            pixels.data() + row * notice.width * 4, notice.width * 4);
        }
        notice_upload->Unmap(0, nullptr);
        D3D12_COMMAND_QUEUE_DESC q{}; q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        check(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)), "CreateCommandQueue");
        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Width = width; desc.Height = height; desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1; desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; desc.BufferCount = 2;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD; desc.Scaling = DXGI_SCALING_STRETCH;
        desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        ComPtr<IDXGISwapChain1> base;
        check(factory->CreateSwapChainForHwnd(queue.Get(), window, &desc, nullptr, nullptr, &base), "CreateSwapChainForHwnd");
        check(base.As(&swap), "QuerySwapChain3");
        check(factory->MakeWindowAssociation(window, DXGI_MWA_NO_ALT_ENTER), "MakeWindowAssociation");
        D3D12_DESCRIPTOR_HEAP_DESC h{}; h.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV; h.NumDescriptors = 2;
        check(device->CreateDescriptorHeap(&h, IID_PPV_ARGS(&heap)), "CreateDescriptorHeap");
        stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        auto handle = heap->GetCPUDescriptorHandleForHeapStart();
        for (UINT i = 0; i < 2; ++i) {
            check(swap->GetBuffer(i, IID_PPV_ARGS(&buffers[i])), "GetBuffer");
            device->CreateRenderTargetView(buffers[i].Get(), nullptr, handle); handle.ptr += stride;
        }
        check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "CreateCommandAllocator");
        check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
              IID_PPV_ARGS(&commands)), "CreateCommandList");
        check(commands->Close(), "CloseCommandList");
        check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event) throw std::runtime_error("CreateEvent failed");
    }
    void draw(double blend, int remaining = CountdownSeconds) {
        UINT index = swap->GetCurrentBackBufferIndex();
        check(allocator->Reset(), "ResetAllocator");
        check(commands->Reset(allocator.Get(), nullptr), "ResetCommandList");
        D3D12_RESOURCE_BARRIER b{}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition.pResource = buffers[index].Get();
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
        b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        commands->ResourceBarrier(1, &b);
        auto handle = heap->GetCPUDescriptorHandleForHeapStart(); handle.ptr += index * stride;
        for (const auto& patch : scene) {
            auto color = patch.moon ? moon_color(blend) : patch.color;
            float rgba[] = {color[0] / 255.f, color[1] / 255.f, color[2] / 255.f, 1.f};
            commands->ClearRenderTargetView(handle, rgba, 1, &patch.rect);
        }
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST; commands->ResourceBarrier(1, &b);
        D3D12_TEXTURE_COPY_LOCATION source{}; source.pResource = notice_upload.Get();
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint.Offset = notice_frame_bytes * (CountdownSeconds - std::clamp(remaining, 0, CountdownSeconds));
        source.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM,
            static_cast<UINT>(notice.width), static_cast<UINT>(notice.height), 1, notice_pitch};
        D3D12_TEXTURE_COPY_LOCATION destination{}; destination.pResource = buffers[index].Get();
        destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        commands->CopyTextureRegion(&destination, notice.x, notice.y, 0, &source, nullptr);
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT; commands->ResourceBarrier(1, &b);
        check(commands->Close(), "CloseCommandList");
        ID3D12CommandList* lists[] = {commands.Get()}; queue->ExecuteCommandLists(1, lists);
        check(swap->Present(1, 0), "Present"); check(queue->Signal(fence.Get(), ++serial), "SignalFence");
        if (fence->GetCompletedValue() < serial) {
            check(fence->SetEventOnCompletion(serial, event), "SetEventOnCompletion");
            if (WaitForSingleObject(event, 2000) != WAIT_OBJECT_0) throw std::runtime_error("GPU fence timed out");
        }
    }
};
struct ImageBuffer { unsigned char* data; int32_t width, height, channels, step; };
struct CaptureLibrary {
    HMODULE library = nullptr;
    void* (__cdecl* create)(HWND, uint64_t) = nullptr;
    uint8_t (__cdecl* connect)(void*) = nullptr;
    uint8_t (__cdecl* capture)(void*, ImageBuffer*) = nullptr;
    void (__cdecl* inactive)(void*) = nullptr;
    void (__cdecl* destroy)(void*) = nullptr;
    ~CaptureLibrary() { if (library) FreeLibrary(library); }
    template<class T> void load_function(T& function, const char* name) {
        function = reinterpret_cast<T>(GetProcAddress(library, name));
        if (!function) throw std::runtime_error(std::string("Missing capture API: ") + name);
    }
    void load(const std::filesystem::path& path) {
        library = LoadLibraryExW(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!library) throw std::runtime_error("Cannot load MaaWin32Screencap.dll");
        load_function(create, "MaaWSManagerCreate"); load_function(connect, "MaaWSManagerConnect");
        load_function(capture, "MaaWSManagerScreencap"); load_function(inactive, "MaaWSManagerInactive");
        load_function(destroy, "MaaWSManagerDestroy");
    }
};
struct CaptureManager {
    CaptureLibrary& api; void* value;
    ~CaptureManager() { if (value) { api.inactive(value); api.destroy(value); } }
};
struct State {
    std::atomic<int> phase{0}, presented{-1};
    std::atomic<long long> presented_at{0};
    std::atomic<bool> stop{false}, done{false};
};
void set_phase(State& state, int phase) {
    if (state.presented == phase) return;
    // Keep each settled appearance for at least 250 ms, in addition to the 220 ms fade.
    while (state.phase != phase && Clock::now().time_since_epoch() <
           std::chrono::milliseconds(state.presented_at.load() + 250)) {
        if (state.stop) throw std::runtime_error("Test window closed");
        Sleep(10);
    }
    state.phase = phase;
    auto deadline = Clock::now() + std::chrono::seconds(3);
    while (state.presented != phase) {
        if (state.stop) throw std::runtime_error("Test window closed");
        if (Clock::now() > deadline) throw std::runtime_error("Pattern presentation timed out");
        Sleep(10);
    }
}
double validate(const ImageBuffer& image, const Options& o, const std::vector<Patch>& scene, int phase) {
    if (!image.data || image.width != o.width || image.height != o.height || (image.channels != 3 && image.channels != 4))
        throw std::runtime_error("Invalid image dimensions or channels");
    int step = image.step > 0 ? image.step : image.width * image.channels;
    if (step < image.width * image.channels) throw std::runtime_error("Invalid image stride");
    double maximum = 0;
    auto notice = notice_layout(o.width, o.height);
    std::vector<POINT> points;
    for (int row = 0; row < 6; ++row) for (int col = 0; col < 8; ++col)
        points.push_back({(2 * col + 1) * image.width / 16, (2 * row + 1) * image.height / 12});
    points.push_back({image.width * 72 / 100, image.height * 24 / 100}); // Fresh-frame marker.
    for (auto center : points) {
        for (int dy : {-2, 0, 2}) for (int dx : {-2, 0, 2}) {
            int x = center.x + dx, y = center.y + dy;
            // Text is localized and antialiased; validate the landscape and moon instead.
            if (x >= notice.x && x < notice.x + notice.width &&
                y >= notice.y && y < notice.y + notice.height) continue;
            auto expected = scene_color(scene, center.x + dx, center.y + dy, phase);
            auto pixel = image.data + (center.y + dy) * step + (center.x + dx) * image.channels;
            for (int c = 0; c < 3; ++c) maximum = std::max(maximum, double(std::abs(pixel[2 - c] - expected[c])));
        }
    }
    return maximum;
}
int self_test() {
    // Deterministic validator regression without a desktop or GPU (also run during release builds).
    Options o; o.width = 640; o.height = 480;
    auto notice = notice_layout(o.width, o.height);
    if (countdown_seconds(std::chrono::milliseconds(0)) != 5 ||
        countdown_seconds(std::chrono::milliseconds(999)) != 5 ||
        countdown_seconds(std::chrono::seconds(1)) != 4 ||
        countdown_seconds(std::chrono::seconds(2)) != 3 ||
        countdown_seconds(std::chrono::seconds(5)) != 0 ||
        countdown_seconds(std::chrono::seconds(90)) != 0) return 1;
    auto text = raster_notice(notice, 5);
    if (text == raster_notice(notice, 4)) return 1; // The final row must actually change.
    for (int row = 0; row < NoticeRows; ++row) {
        int count = 0;
        int top = static_cast<int>(12 + row * notice.font_size * 1.6f);
        int bottom = static_cast<int>(12 + (row + 1) * notice.font_size * 1.6f);
        for (int y = top; y < bottom; ++y) for (int x = 12; x < notice.width - 12; ++x)
            if (text[(y * notice.width + x) * 4] > 40) ++count;
        if (count < 20) return 1; // Four language rows and the countdown must all render.
    }
    auto scene = make_scene(o.width, o.height);
    for (int channels : {3, 4}) {
        int stride = o.width * channels + 8;
        std::vector<unsigned char> pixels(stride * o.height, 255);
        ImageBuffer image{pixels.data(), o.width, o.height, channels, stride};
        if (validate(image, o, scene, 0) <= ColorTolerance) return 1; // White frames must fail.
        std::fill(pixels.begin(), pixels.end(), static_cast<unsigned char>(0));
        if (validate(image, o, scene, 0) <= ColorTolerance) return 1; // Dark is not the same as blank.
        for (int y = 0; y < o.height; ++y) for (int x = 0; x < o.width; ++x) {
            auto color = scene_color(scene, x, y, 0);
            for (int c = 0; c < 3; ++c) pixels[y * stride + x * channels + c] = static_cast<unsigned char>(color[2-c]);
        }
        if (validate(image, o, scene, 0) != 0 || validate(image, o, scene, 1) <= ColorTolerance) return 1;
        image.width = 1;
        bool rejected = false;
        try { validate(image, o, scene, 0); } catch (const std::runtime_error&) { rejected = true; }
        if (!rejected) return 1;
    }
    return 0;
}
void benchmark(HWND window, const Options& o, State& state) {
    std::vector<Result> results;
    try {
        CaptureLibrary api; api.load(o.dll);
        auto scene = make_scene(o.width, o.height);
        int phase = 0;
        const std::array<const char*, 6> modes = {"gdi", "framepool", "dxgi_desktop_dup", "dxgi_desktop_dup_window", "printwindow", "screendc"};
        for (size_t method = 0; method < modes.size(); ++method) {
            if (state.stop) throw std::runtime_error("Test window closed");
            Result r; r.mode = modes[method];
            try {
                set_phase(state, phase);
                CaptureManager manager{api, api.create(window, uint64_t{1} << method)};
                if (!manager.value || !api.connect(manager.value)) throw std::runtime_error("Capture connection failed");
                // Connection already warms up the native backend. Count the first matching
                // validation frame as a timing sample instead of taking redundant captures.
                for (int pattern = 0; pattern < 2; ++pattern) {
                    if (pattern) ++phase;
                    set_phase(state, phase);
                    for (int sample = 0; sample < 3; ++sample) {
                        bool matched = false;
                        for (int attempt = 0; attempt < (sample == 0 ? 5 : 1); ++attempt) {
                            if (state.stop) throw std::runtime_error("Test window closed");
                            ImageBuffer image{}; auto started = Clock::now();
                            bool captured = api.capture(manager.value, &image) != 0;
                            auto elapsed = std::chrono::duration<double, std::milli>(Clock::now() - started).count();
                            auto error = captured ? validate(image, o, scene, phase) : 256;
                            if (error <= ColorTolerance) {
                                r.error_max = std::max(r.error_max, error);
                                r.samples.push_back(elapsed); matched = true; break;
                            }
                            if (sample == 0 && attempt < 4) Sleep(25); // Drain stale WGC frames.
                        }
                        if (!matched) throw std::runtime_error("Color pattern mismatch or stale frame");
                    }
                }
                r.valid = true;
            } catch (const std::exception& error) { r.error = error.what(); }
            // Each manager dies before the next method: never duplicate an output twice in this process.
            results.push_back(r); report(o, results, false);
        }
        report(o, results, true);
    } catch (const std::exception& error) { try { report(o, results, true, error.what()); } catch (...) {} }
    state.done = true; PostMessageW(window, WM_CLOSE, 0, 0);
}
LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_ERASEBKGND) return 1;
    if (message == WM_KEYDOWN && wparam == VK_ESCAPE) { DestroyWindow(window); return 0; }
    if (message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    Options o;
    try {
        int argc = 0; auto argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        if (!argv) return 2;
        if (argc == 2 && std::wstring(argv[1]) == L"--self-test") {
            LocalFree(argv); return self_test();
        }
        for (int i = 1; i + 1 < argc; i += 2) {
            std::wstring key = argv[i], value = argv[i + 1];
            if (key == L"--dll") o.dll = value;
            else if (key == L"--report") o.report = value;
            else if (key == L"--x") o.x = std::stoi(value);
            else if (key == L"--y") o.y = std::stoi(value);
            else if (key == L"--width") o.width = std::stoi(value);
            else if (key == L"--height") o.height = std::stoi(value);
            else throw std::runtime_error("Unknown argument");
        }
        LocalFree(argv);
        if (o.dll.empty() || o.report.empty() || o.width < 320 || o.height < 240 || o.width > 16384 || o.height > 16384) return 2;
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        WNDCLASSW wc{}; wc.lpfnWndProc = window_proc; wc.hInstance = instance;
        wc.lpszClassName = L"NightreignCaptureProbe"; wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        if (!RegisterClassW(&wc)) throw std::runtime_error("RegisterClass failed");
        HWND window = CreateWindowExW(WS_EX_TOPMOST, wc.lpszClassName, L"DirectX capture test - Esc to cancel", WS_POPUP,
            o.x, o.y, o.width, o.height, nullptr, nullptr, instance, nullptr);
        if (!window) throw std::runtime_error("CreateWindow failed");
        Renderer renderer; renderer.initialize(window, o.width, o.height);
        renderer.draw(0); // Populate the swap chain before showing the window.
        ShowWindow(window, SW_SHOW); SetForegroundWindow(window);
        const auto visible_since = Clock::now();
        State state; std::thread worker([&] { benchmark(window, o, state); });
        std::string render_error;
        try {
            int drawing_phase = 0;
            double from = 0, blend = 0;
            auto transition = Clock::now() - std::chrono::seconds(1);
            while (!state.done && !state.stop) {
                MSG message{};
                while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
                    if (message.message == WM_QUIT) state.stop = true;
                    TranslateMessage(&message); DispatchMessageW(&message);
                }
                if (state.stop || state.done) break;
                int phase = state.phase;
                if (phase != drawing_phase) {
                    from = blend; drawing_phase = phase; transition = Clock::now();
                }
                double progress = std::clamp(std::chrono::duration<double, std::milli>(Clock::now() - transition).count() / 220., 0., 1.);
                double eased = progress * progress * (3 - 2 * progress);
                blend = from + ((phase % 2) - from) * eased;
                renderer.draw(blend, countdown_seconds(Clock::now() - visible_since));
                if (progress >= 1 && state.presented != phase) {
                    state.presented_at = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now().time_since_epoch()).count();
                    state.presented = phase;
                }
            }
        } catch (const std::exception& error) { render_error = error.what(); state.stop = true; }
        worker.join();
        if (!render_error.empty()) report(o, {}, true, render_error);
        if (IsWindow(window)) DestroyWindow(window);
        return 0;
    } catch (const std::exception& error) {
        if (!o.report.empty()) { try { report(o, {}, true, error.what()); } catch (...) {} }
        return 1;
    }
}
