#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <array>
#include <bit>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <io.h>
#include <process.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace {

constexpr std::uint64_t EMPTY = std::numeric_limits<std::uint64_t>::max();
constexpr std::uint64_t TOMBSTONE = EMPTY - 1ULL;
constexpr int BITS = 21;
constexpr std::int64_t BIAS = 1LL << (BITS - 1);
constexpr std::int64_t AXIS_MIN = -BIAS;
constexpr std::int64_t AXIS_MAX = BIAS - 1;
constexpr std::uint64_t AXIS_MASK = (1ULL << BITS) - 1ULL;

struct Voxel {
    std::uint64_t key = EMPTY;
    std::uint64_t last_seen_ns = 0;
    std::uint64_t last_frame_revision = 0;
    float cx = 0.0F;
    float cy = 0.0F;
    float cz = 0.0F;
    std::uint32_t count = 0;
    float min_z = 0.0F;
    float max_z = 0.0F;
};

struct IntegrateStats {
    std::uint64_t revision = 0;
    std::uint64_t input_points = 0;
    std::uint64_t accepted_points = 0;
    std::uint64_t unique_input_voxels = 0;
    std::uint64_t invalid_points = 0;
    std::uint64_t coordinate_overflow_points = 0;
    std::uint64_t total_voxels = 0;
    std::uint64_t evicted_voxels_total = 0;
    std::vector<std::uint32_t> touched;
    std::vector<std::uint64_t> removed;
};

bool host_big_endian() {
    const std::uint16_t v = 0x0102U;
    const auto b = std::bit_cast<std::array<unsigned char, 2>>(v);
    return b[0] == 0x01U;
}

std::uint16_t swap16(std::uint16_t v) {
    return static_cast<std::uint16_t>((v >> 8U) | (v << 8U));
}

std::uint32_t swap32(std::uint32_t v) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_bswap32(v);
#else
    return ((v & 0x000000FFU) << 24U)
        | ((v & 0x0000FF00U) << 8U)
        | ((v & 0x00FF0000U) >> 8U)
        | ((v & 0xFF000000U) >> 24U);
#endif
}

std::uint64_t swap64(std::uint64_t v) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_bswap64(v);
#else
    v = ((v & 0x00000000FFFFFFFFULL) << 32U)
      | ((v & 0xFFFFFFFF00000000ULL) >> 32U);
    v = ((v & 0x0000FFFF0000FFFFULL) << 16U)
      | ((v & 0xFFFF0000FFFF0000ULL) >> 16U);
    v = ((v & 0x00FF00FF00FF00FFULL) << 8U)
      | ((v & 0xFF00FF00FF00FF00ULL) >> 8U);
    return v;
#endif
}

template <typename T>
T load_int(const std::uint8_t* p, bool source_big) {
    T value {};
    std::memcpy(&value, p, sizeof(T));
    if (sizeof(T) == 1 || source_big == host_big_endian()) {
        return value;
    }
    if constexpr (sizeof(T) == 2) {
        auto bits = std::bit_cast<std::uint16_t>(value);
        return std::bit_cast<T>(swap16(bits));
    }
    if constexpr (sizeof(T) == 4) {
        auto bits = std::bit_cast<std::uint32_t>(value);
        return std::bit_cast<T>(swap32(bits));
    }
    if constexpr (sizeof(T) == 8) {
        auto bits = std::bit_cast<std::uint64_t>(value);
        return std::bit_cast<T>(swap64(bits));
    }
    return value;
}

int datatype_size(int t) {
    switch (t) {
        case 1: case 2: return 1;
        case 3: case 4: return 2;
        case 5: case 6: case 7: return 4;
        case 8: return 8;
        default: return 0;
    }
}

double load_scalar(const std::uint8_t* p, int t, bool source_big) {
    switch (t) {
        case 1: return static_cast<double>(load_int<std::int8_t>(p, source_big));
        case 2: return static_cast<double>(load_int<std::uint8_t>(p, source_big));
        case 3: return static_cast<double>(load_int<std::int16_t>(p, source_big));
        case 4: return static_cast<double>(load_int<std::uint16_t>(p, source_big));
        case 5: return static_cast<double>(load_int<std::int32_t>(p, source_big));
        case 6: return static_cast<double>(load_int<std::uint32_t>(p, source_big));
        case 7: {
            std::uint32_t bits {};
            std::memcpy(&bits, p, sizeof(bits));
            if (source_big != host_big_endian()) bits = swap32(bits);
            return static_cast<double>(std::bit_cast<float>(bits));
        }
        case 8: {
            std::uint64_t bits {};
            std::memcpy(&bits, p, sizeof(bits));
            if (source_big != host_big_endian()) bits = swap64(bits);
            return std::bit_cast<double>(bits);
        }
        default:
            throw std::invalid_argument("unsupported PointField datatype");
    }
}

std::uint64_t mix64(std::uint64_t x) {
    x ^= x >> 30U;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27U;
    x *= 0x94d049bb133111ebULL;
    x ^= x >> 31U;
    return x;
}

bool pack_key(double x, double y, double z, double voxel, std::uint64_t& key) {
    const auto ix = static_cast<std::int64_t>(std::floor(x / voxel));
    const auto iy = static_cast<std::int64_t>(std::floor(y / voxel));
    const auto iz = static_cast<std::int64_t>(std::floor(z / voxel));
    if (ix < AXIS_MIN || ix > AXIS_MAX
        || iy < AXIS_MIN || iy > AXIS_MAX
        || iz < AXIS_MIN || iz > AXIS_MAX) {
        return false;
    }
    const auto ux = static_cast<std::uint64_t>(ix + BIAS);
    const auto uy = static_cast<std::uint64_t>(iy + BIAS);
    const auto uz = static_cast<std::uint64_t>(iz + BIAS);
    key = (ux << (BITS * 2)) | (uy << BITS) | uz;
    return true;
}

std::array<std::int32_t, 3> decode_key(std::uint64_t key) {
    const auto ux = (key >> (BITS * 2)) & AXIS_MASK;
    const auto uy = (key >> BITS) & AXIS_MASK;
    const auto uz = key & AXIS_MASK;
    return {
        static_cast<std::int32_t>(static_cast<std::int64_t>(ux) - BIAS),
        static_cast<std::int32_t>(static_cast<std::int64_t>(uy) - BIAS),
        static_cast<std::int32_t>(static_cast<std::int64_t>(uz) - BIAS),
    };
}

std::size_t next_pow2(std::size_t value) {
    std::size_t result = 8;
    while (result < value) {
        if (result > std::numeric_limits<std::size_t>::max() / 2) {
            throw std::overflow_error("hash table size overflow");
        }
        result <<= 1U;
    }
    return result;
}

class FlatIndex {
public:
    explicit FlatIndex(std::size_t capacity)
        : keys_(next_pow2(std::max<std::size_t>(capacity * 2, 8)), EMPTY),
          slots_(keys_.size(), 0),
          mask_(keys_.size() - 1) {}

    bool find(std::uint64_t key, std::uint32_t& slot) const {
        std::size_t pos = static_cast<std::size_t>(mix64(key)) & mask_;
        for (std::size_t n = 0; n < keys_.size(); ++n) {
            const auto observed = keys_[pos];
            if (observed == EMPTY) return false;
            if (observed == key) {
                slot = slots_[pos];
                return true;
            }
            pos = (pos + 1U) & mask_;
        }
        return false;
    }

    void insert(std::uint64_t key, std::uint32_t slot) {
        std::size_t pos = static_cast<std::size_t>(mix64(key)) & mask_;
        std::size_t tomb = keys_.size();
        for (std::size_t n = 0; n < keys_.size(); ++n) {
            const auto observed = keys_[pos];
            if (observed == key) {
                slots_[pos] = slot;
                return;
            }
            if (observed == TOMBSTONE && tomb == keys_.size()) tomb = pos;
            if (observed == EMPTY) {
                const auto target = tomb != keys_.size() ? tomb : pos;
                keys_[target] = key;
                slots_[target] = slot;
                return;
            }
            pos = (pos + 1U) & mask_;
        }
        if (tomb != keys_.size()) {
            keys_[tomb] = key;
            slots_[tomb] = slot;
            return;
        }
        throw std::runtime_error("voxel hash table is full");
    }

    void erase(std::uint64_t key) {
        std::size_t pos = static_cast<std::size_t>(mix64(key)) & mask_;
        for (std::size_t n = 0; n < keys_.size(); ++n) {
            const auto observed = keys_[pos];
            if (observed == EMPTY) return;
            if (observed == key) {
                keys_[pos] = TOMBSTONE;
                return;
            }
            pos = (pos + 1U) & mask_;
        }
    }

    std::size_t bytes() const {
        return keys_.capacity() * sizeof(std::uint64_t)
            + slots_.capacity() * sizeof(std::uint32_t);
    }

private:
    std::vector<std::uint64_t> keys_;
    std::vector<std::uint32_t> slots_;
    std::size_t mask_;
};

class VoxelMapCore {
public:
    VoxelMapCore(std::size_t max_voxels, std::size_t eviction_window)
        : max_voxels_(std::max<std::size_t>(max_voxels, 1)),
          eviction_window_(std::max<std::size_t>(
              std::min(eviction_window, max_voxels_), 1)),
          voxels_(max_voxels_),
          index_(max_voxels_) {
        touched_.reserve(32768);
        removed_.reserve(1024);
    }

    IntegrateStats integrate(
        const std::uint8_t* data,
        std::size_t nbytes,
        std::size_t width,
        std::size_t height,
        std::size_t row_step,
        std::size_t point_step,
        bool big_endian,
        int x_offset,
        int x_type,
        int y_offset,
        int y_type,
        int z_offset,
        int z_type,
        std::size_t stride,
        double voxel_size,
        std::uint64_t timestamp_ns
    ) {
        if (!std::isfinite(voxel_size) || voxel_size <= 0.0) {
            throw std::invalid_argument("voxel_size_m must be positive and finite");
        }
        if (stride == 0 || point_step == 0) {
            throw std::invalid_argument("point stride and point_step must be positive");
        }
        if (height && row_step && nbytes < row_step * height) {
            throw std::invalid_argument("point-cloud buffer smaller than row_step * height");
        }

        const auto check = [point_step](int offset, int type, const char* name) {
            const int size = datatype_size(type);
            if (size == 0) {
                throw std::invalid_argument(std::string("unsupported datatype for ") + name);
            }
            if (offset < 0
                || static_cast<std::size_t>(offset + size) > point_step) {
                throw std::invalid_argument(std::string("invalid offset for ") + name);
            }
        };
        check(x_offset, x_type, "x");
        check(y_offset, y_type, "y");
        check(z_offset, z_type, "z");

        IntegrateStats result;
        result.input_points = width * height;
        touched_.clear();
        removed_.clear();
        const std::uint64_t frame_revision = revision_ + 1;

        const std::size_t total = width * height;
        for (std::size_t linear = 0; linear < total; linear += stride) {
            const std::size_t row = width ? linear / width : 0;
            const std::size_t column = width ? linear % width : 0;
            const std::size_t base = row * row_step + column * point_step;
            if (base + point_step > nbytes) break;

            const auto* point = data + base;
            const double x = load_scalar(point + x_offset, x_type, big_endian);
            const double y = load_scalar(point + y_offset, y_type, big_endian);
            const double z = load_scalar(point + z_offset, z_type, big_endian);

            if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
                ++result.invalid_points;
                continue;
            }

            std::uint64_t key = 0;
            if (!pack_key(x, y, z, voxel_size, key)) {
                ++result.coordinate_overflow_points;
                continue;
            }

            const auto slot = ensure_slot(key, timestamp_ns);
            auto& voxel = voxels_[slot];

            if (voxel.last_frame_revision != frame_revision) {
                voxel.last_frame_revision = frame_revision;
                touched_.push_back(slot);
                ++result.unique_input_voxels;
            }

            const auto old_count = voxel.count;
            if (old_count == 0) {
                voxel.cx = static_cast<float>(x);
                voxel.cy = static_cast<float>(y);
                voxel.cz = static_cast<float>(z);
                voxel.min_z = static_cast<float>(z);
                voxel.max_z = static_cast<float>(z);
                voxel.count = 1;
            } else {
                const std::uint32_t new_count = old_count == UINT32_MAX
                    ? UINT32_MAX
                    : old_count + 1U;
                const double denom = static_cast<double>(old_count) + 1.0;
                voxel.cx = static_cast<float>(
                    static_cast<double>(voxel.cx)
                    + (x - static_cast<double>(voxel.cx)) / denom);
                voxel.cy = static_cast<float>(
                    static_cast<double>(voxel.cy)
                    + (y - static_cast<double>(voxel.cy)) / denom);
                voxel.cz = static_cast<float>(
                    static_cast<double>(voxel.cz)
                    + (z - static_cast<double>(voxel.cz)) / denom);
                voxel.count = new_count;
                voxel.min_z = std::min(voxel.min_z, static_cast<float>(z));
                voxel.max_z = std::max(voxel.max_z, static_cast<float>(z));
            }
            voxel.last_seen_ns = timestamp_ns;
            ++result.accepted_points;
        }

        std::sort(touched_.begin(), touched_.end());
        touched_.erase(
            std::unique(touched_.begin(), touched_.end()),
            touched_.end()
        );

        ++revision_;
        ++frames_;
        input_points_ += result.input_points;
        accepted_points_ += result.accepted_points;
        unique_input_voxels_ += result.unique_input_voxels;
        invalid_points_ += result.invalid_points;
        overflow_points_ += result.coordinate_overflow_points;

        result.revision = revision_;
        result.total_voxels = size_;
        result.evicted_voxels_total = evicted_voxels_;
        result.touched = touched_;
        result.removed = removed_;
        return result;
    }

    const std::vector<Voxel>& voxels() const { return voxels_; }
    std::size_t size() const { return size_; }
    std::uint64_t revision() const { return revision_; }
    std::size_t max_voxels() const { return max_voxels_; }
    std::uint64_t frames() const { return frames_; }
    std::uint64_t input_points() const { return input_points_; }
    std::uint64_t accepted_points() const { return accepted_points_; }
    std::uint64_t unique_input_voxels() const { return unique_input_voxels_; }
    std::uint64_t evicted_voxels() const { return evicted_voxels_; }
    std::uint64_t invalid_points() const { return invalid_points_; }
    std::uint64_t overflow_points() const { return overflow_points_; }

    std::size_t state_bytes() const {
        return voxels_.capacity() * sizeof(Voxel)
            + index_.bytes()
            + touched_.capacity() * sizeof(std::uint32_t)
            + removed_.capacity() * sizeof(std::uint64_t);
    }

private:
    std::uint32_t select_eviction_slot() {
        if (size_ == 0) throw std::runtime_error("cannot evict empty map");
        const std::size_t window = std::min(eviction_window_, size_);
        std::size_t selected = eviction_cursor_ % size_;
        std::uint64_t oldest = voxels_[selected].last_seen_ns;
        for (std::size_t offset = 1; offset < window; ++offset) {
            const std::size_t slot = (eviction_cursor_ + offset) % size_;
            if (voxels_[slot].last_seen_ns < oldest) {
                selected = slot;
                oldest = voxels_[slot].last_seen_ns;
            }
        }
        eviction_cursor_ = (selected + 1U) % size_;
        return static_cast<std::uint32_t>(selected);
    }

    std::uint32_t ensure_slot(std::uint64_t key, std::uint64_t timestamp_ns) {
        std::uint32_t slot = 0;
        if (index_.find(key, slot)) return slot;

        if (size_ < max_voxels_) {
            slot = static_cast<std::uint32_t>(size_++);
        } else {
            slot = select_eviction_slot();
            removed_.push_back(voxels_[slot].key);
            index_.erase(voxels_[slot].key);
            ++evicted_voxels_;
        }

        auto& voxel = voxels_[slot];
        voxel = Voxel {};
        voxel.key = key;
        voxel.last_seen_ns = timestamp_ns;
        index_.insert(key, slot);
        return slot;
    }

    std::size_t max_voxels_;
    std::size_t eviction_window_;
    std::vector<Voxel> voxels_;
    FlatIndex index_;
    std::vector<std::uint32_t> touched_;
    std::vector<std::uint64_t> removed_;
    std::size_t size_ = 0;
    std::size_t eviction_cursor_ = 0;
    std::uint64_t revision_ = 0;
    std::uint64_t frames_ = 0;
    std::uint64_t input_points_ = 0;
    std::uint64_t accepted_points_ = 0;
    std::uint64_t unique_input_voxels_ = 0;
    std::uint64_t evicted_voxels_ = 0;
    std::uint64_t invalid_points_ = 0;
    std::uint64_t overflow_points_ = 0;
};

VoxelMapCore* get_core(PyObject* capsule) {
    return static_cast<VoxelMapCore*>(
        PyCapsule_GetPointer(capsule, "nodrix_mapping.VoxelMapCore"));
}

void destroy_core(PyObject* capsule) {
    void* pointer = PyCapsule_GetPointer(
        capsule, "nodrix_mapping.VoxelMapCore");
    if (pointer) delete static_cast<VoxelMapCore*>(pointer);
    else PyErr_Clear();
}

bool dict_set_owned(PyObject* dict, const char* key, PyObject* value) {
    if (!value) return false;
    const int rc = PyDict_SetItemString(dict, key, value);
    Py_DECREF(value);
    return rc == 0;
}

PyObject* bytes_copy(const void* data, std::size_t nbytes) {
    if (nbytes > static_cast<std::size_t>(PY_SSIZE_T_MAX)) {
        PyErr_SetString(PyExc_OverflowError, "native mapping output too large");
        return nullptr;
    }
    return PyBytes_FromStringAndSize(
        static_cast<const char*>(data),
        static_cast<Py_ssize_t>(nbytes));
}

PyObject* build_arrays(
    const VoxelMapCore& core,
    const std::vector<std::uint32_t>* slots,
    const std::vector<std::uint64_t>* removed
) {
    const std::size_t count = slots ? slots->size() : core.size();
    std::vector<std::int32_t> indices(count * 3);
    std::vector<float> centroids(count * 3);
    std::vector<std::uint32_t> counts(count);
    std::vector<float> min_z(count);
    std::vector<float> max_z(count);
    const auto& voxels = core.voxels();

    for (std::size_t i = 0; i < count; ++i) {
        const std::size_t slot = slots ? (*slots)[i] : i;
        const auto& v = voxels[slot];
        const auto decoded = decode_key(v.key);
        indices[i * 3] = decoded[0];
        indices[i * 3 + 1] = decoded[1];
        indices[i * 3 + 2] = decoded[2];
        centroids[i * 3] = v.cx;
        centroids[i * 3 + 1] = v.cy;
        centroids[i * 3 + 2] = v.cz;
        counts[i] = v.count;
        min_z[i] = v.min_z;
        max_z[i] = v.max_z;
    }

    PyObject* result = PyDict_New();
    if (!result) return nullptr;

    auto add_bytes = [&](const char* name, const void* ptr, std::size_t n) {
        return dict_set_owned(result, name, bytes_copy(ptr, n));
    };

    if (!add_bytes("indices", indices.data(), indices.size() * sizeof(std::int32_t))
        || !add_bytes("centroids", centroids.data(), centroids.size() * sizeof(float))
        || !add_bytes("counts", counts.data(), counts.size() * sizeof(std::uint32_t))
        || !add_bytes("min_z", min_z.data(), min_z.size() * sizeof(float))
        || !add_bytes("max_z", max_z.data(), max_z.size() * sizeof(float))
        || !dict_set_owned(result, "count", PyLong_FromSize_t(count))) {
        Py_DECREF(result);
        return nullptr;
    }

    if (removed) {
        std::vector<std::int32_t> removed_indices(removed->size() * 3);
        for (std::size_t i = 0; i < removed->size(); ++i) {
            const auto decoded = decode_key((*removed)[i]);
            removed_indices[i * 3] = decoded[0];
            removed_indices[i * 3 + 1] = decoded[1];
            removed_indices[i * 3 + 2] = decoded[2];
        }
        if (!add_bytes(
            "removed_indices",
            removed_indices.data(),
            removed_indices.size() * sizeof(std::int32_t))) {
            Py_DECREF(result);
            return nullptr;
        }
    }
    return result;
}

PyObject* py_create(PyObject*, PyObject* args, PyObject* kwargs) {
    unsigned long long max_voxels = 0;
    unsigned long long eviction_window = 0;
    static const char* names[] = {
        "max_voxels", "eviction_window", nullptr
    };
    if (!PyArg_ParseTupleAndKeywords(
        args, kwargs, "KK", const_cast<char**>(names),
        &max_voxels, &eviction_window)) {
        return nullptr;
    }
    try {
        auto* core = new VoxelMapCore(
            static_cast<std::size_t>(max_voxels),
            static_cast<std::size_t>(eviction_window));
        return PyCapsule_New(
            core, "nodrix_mapping.VoxelMapCore", destroy_core);
    } catch (const std::exception& exc) {
        PyErr_SetString(PyExc_RuntimeError, exc.what());
        return nullptr;
    }
}

PyObject* py_integrate(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* capsule = nullptr;
    PyObject* buffer_object = nullptr;
    int width = 0, height = 0, row_step = 0, point_step = 0;
    int big = 0;
    int xo = 0, xt = 0, yo = 0, yt = 0, zo = 0, zt = 0;
    int stride = 0;
    double voxel = 0.0;
    unsigned long long timestamp_ns = 0;

    static const char* names[] = {
        "core", "buffer", "width", "height", "row_step", "point_step",
        "is_bigendian", "x_offset", "x_datatype", "y_offset", "y_datatype",
        "z_offset", "z_datatype", "point_stride", "voxel_size_m",
        "timestamp_ns", nullptr
    };

    if (!PyArg_ParseTupleAndKeywords(
        args, kwargs, "OOiiiipiiiiiiidK", const_cast<char**>(names),
        &capsule, &buffer_object, &width, &height, &row_step, &point_step,
        &big, &xo, &xt, &yo, &yt, &zo, &zt, &stride, &voxel, &timestamp_ns)) {
        return nullptr;
    }

    if (width < 0 || height < 0 || row_step < 0 || point_step <= 0 || stride <= 0) {
        PyErr_SetString(PyExc_ValueError, "invalid point-cloud shape/stride");
        return nullptr;
    }

    auto* core = get_core(capsule);
    if (!core) return nullptr;

    Py_buffer view {};
    if (PyObject_GetBuffer(buffer_object, &view, PyBUF_CONTIG_RO) != 0) {
        return nullptr;
    }

    IntegrateStats stats;
    std::string error;
    Py_BEGIN_ALLOW_THREADS
    try {
        stats = core->integrate(
            static_cast<const std::uint8_t*>(view.buf),
            static_cast<std::size_t>(view.len),
            static_cast<std::size_t>(width),
            static_cast<std::size_t>(height),
            static_cast<std::size_t>(row_step),
            static_cast<std::size_t>(point_step),
            big != 0, xo, xt, yo, yt, zo, zt,
            static_cast<std::size_t>(stride),
            voxel,
            static_cast<std::uint64_t>(timestamp_ns));
    } catch (const std::exception& exc) {
        error = exc.what();
    }
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&view);

    if (!error.empty()) {
        PyErr_SetString(PyExc_RuntimeError, error.c_str());
        return nullptr;
    }

    PyObject* result = build_arrays(*core, &stats.touched, &stats.removed);
    if (!result) return nullptr;

    auto add = [&](const char* name, std::uint64_t value) {
        return dict_set_owned(
            result, name, PyLong_FromUnsignedLongLong(value));
    };

    if (!add("revision", stats.revision)
        || !add("input_points", stats.input_points)
        || !add("accepted_points", stats.accepted_points)
        || !add("unique_input_voxels", stats.unique_input_voxels)
        || !add("invalid_points", stats.invalid_points)
        || !add("coordinate_overflow_points", stats.coordinate_overflow_points)
        || !add("total_voxels", stats.total_voxels)
        || !add("evicted_voxels_total", stats.evicted_voxels_total)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* py_snapshot(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    if (!PyArg_ParseTuple(args, "O", &capsule)) return nullptr;
    auto* core = get_core(capsule);
    if (!core) return nullptr;

    PyObject* result = build_arrays(*core, nullptr, nullptr);
    if (!result) return nullptr;
    if (!dict_set_owned(
        result, "revision", PyLong_FromUnsignedLongLong(core->revision()))) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* py_stats(PyObject*, PyObject* args) {
    PyObject* capsule = nullptr;
    if (!PyArg_ParseTuple(args, "O", &capsule)) return nullptr;
    auto* core = get_core(capsule);
    if (!core) return nullptr;

    PyObject* result = PyDict_New();
    if (!result) return nullptr;
    auto add = [&](const char* name, std::uint64_t value) {
        return dict_set_owned(
            result, name, PyLong_FromUnsignedLongLong(value));
    };

    if (!add("revision", core->revision())
        || !add("voxel_count", core->size())
        || !add("max_voxels", core->max_voxels())
        || !add("frames", core->frames())
        || !add("input_points", core->input_points())
        || !add("accepted_points", core->accepted_points())
        || !add("unique_input_voxels", core->unique_input_voxels())
        || !add("evicted_voxels", core->evicted_voxels())
        || !add("invalid_points", core->invalid_points())
        || !add("coordinate_overflow_points", core->overflow_points())
        || !add("native_state_bytes", core->state_bytes())) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

struct PlyVertex {
    float x, y, z;
    std::uint32_t observations;
    float min_z, max_z;
};
static_assert(sizeof(PlyVertex) == 24);

bool write_all(std::FILE* f, const void* p, std::size_t n) {
    return std::fwrite(p, 1, n, f) == n;
}

bool flush_file(std::FILE* f, bool durable) {
    if (std::fflush(f) != 0) return false;
    if (!durable) return true;
#if defined(_WIN32)
    return _commit(_fileno(f)) == 0;
#else
    return ::fsync(fileno(f)) == 0;
#endif
}

long pid_value() {
#if defined(_WIN32)
    return static_cast<long>(_getpid());
#else
    return static_cast<long>(::getpid());
#endif
}

void write_ply(
    const std::string& path,
    const float* xyz,
    const std::uint32_t* counts,
    const float* min_z,
    const float* max_z,
    std::size_t count,
    std::uint64_t revision,
    double voxel_size,
    bool durable
) {
    if (host_big_endian()) {
        throw std::runtime_error("native PLY writer requires little-endian host");
    }
    const std::string tmp = path + ".tmp." + std::to_string(pid_value());
    const std::string header =
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment generated by Nodrix mapping.ply_store native\n"
        "comment revision " + std::to_string(revision) + "\n"
        "comment voxel_size_m " + std::to_string(voxel_size) + "\n"
        "element vertex " + std::to_string(count) + "\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uint observations\n"
        "property float min_z\n"
        "property float max_z\n"
        "end_header\n";

    std::FILE* f = std::fopen(tmp.c_str(), "wb");
    if (!f) throw std::runtime_error("cannot open temporary PLY");

    bool ok = write_all(f, header.data(), header.size());
    constexpr std::size_t CHUNK = 4096;
    std::vector<PlyVertex> chunk(std::min<std::size_t>(count, CHUNK));

    for (std::size_t begin = 0; ok && begin < count; begin += CHUNK) {
        const std::size_t length = std::min(CHUNK, count - begin);
        if (chunk.size() < length) chunk.resize(length);
        for (std::size_t i = 0; i < length; ++i) {
            const std::size_t s = begin + i;
            chunk[i] = PlyVertex {
                xyz[s * 3], xyz[s * 3 + 1], xyz[s * 3 + 2],
                counts[s], min_z[s], max_z[s]
            };
        }
        ok = write_all(f, chunk.data(), length * sizeof(PlyVertex));
    }

    if (ok) ok = flush_file(f, durable);
    if (std::fclose(f) != 0) ok = false;

    if (!ok) {
        std::remove(tmp.c_str());
        throw std::runtime_error("failed while writing PLY");
    }

#if defined(_WIN32)
    std::remove(path.c_str());
#endif
    if (std::rename(tmp.c_str(), path.c_str()) != 0) {
        const int e = errno;
        std::remove(tmp.c_str());
        throw std::runtime_error(
            "atomic PLY rename failed: " + std::to_string(e));
    }

#if !defined(_WIN32)
    if (durable) {
        const auto parent = std::filesystem::path(path).parent_path();
        const auto directory = parent.empty() ? std::filesystem::path(".") : parent;
        const int fd = ::open(directory.c_str(), O_RDONLY);
        if (fd >= 0) {
            ::fsync(fd);
            ::close(fd);
        }
    }
#endif
}

PyObject* py_write_ply(PyObject*, PyObject* args, PyObject* kwargs) {
    const char* path = nullptr;
    PyObject *xyz_obj = nullptr, *counts_obj = nullptr;
    PyObject *min_obj = nullptr, *max_obj = nullptr;
    unsigned long long revision = 0;
    double voxel_size = 0.0;
    int durable = 1;

    static const char* names[] = {
        "path", "centroids", "counts", "min_z", "max_z",
        "revision", "voxel_size_m", "durable", nullptr
    };

    if (!PyArg_ParseTupleAndKeywords(
        args, kwargs, "sOOOOKdp", const_cast<char**>(names),
        &path, &xyz_obj, &counts_obj, &min_obj, &max_obj,
        &revision, &voxel_size, &durable)) {
        return nullptr;
    }

    Py_buffer xyz {}, counts {}, minz {}, maxz {};
    auto release_all = [&]() {
        if (xyz.obj) PyBuffer_Release(&xyz);
        if (counts.obj) PyBuffer_Release(&counts);
        if (minz.obj) PyBuffer_Release(&minz);
        if (maxz.obj) PyBuffer_Release(&maxz);
    };

    if (PyObject_GetBuffer(xyz_obj, &xyz, PyBUF_CONTIG_RO) != 0
        || PyObject_GetBuffer(counts_obj, &counts, PyBUF_CONTIG_RO) != 0
        || PyObject_GetBuffer(min_obj, &minz, PyBUF_CONTIG_RO) != 0
        || PyObject_GetBuffer(max_obj, &maxz, PyBUF_CONTIG_RO) != 0) {
        release_all();
        return nullptr;
    }

    const Py_ssize_t triple = 3 * static_cast<Py_ssize_t>(sizeof(float));
    if (xyz.len % triple != 0) {
        release_all();
        PyErr_SetString(PyExc_ValueError, "centroids must be float32 XYZ triples");
        return nullptr;
    }
    const std::size_t count = static_cast<std::size_t>(xyz.len / triple);
    if (counts.len != static_cast<Py_ssize_t>(count * sizeof(std::uint32_t))
        || minz.len != static_cast<Py_ssize_t>(count * sizeof(float))
        || maxz.len != static_cast<Py_ssize_t>(count * sizeof(float))) {
        release_all();
        PyErr_SetString(PyExc_ValueError, "PLY arrays have inconsistent lengths");
        return nullptr;
    }

    std::string error;
    Py_BEGIN_ALLOW_THREADS
    try {
        write_ply(
            path,
            static_cast<const float*>(xyz.buf),
            static_cast<const std::uint32_t*>(counts.buf),
            static_cast<const float*>(minz.buf),
            static_cast<const float*>(maxz.buf),
            count,
            static_cast<std::uint64_t>(revision),
            voxel_size,
            durable != 0);
    } catch (const std::exception& exc) {
        error = exc.what();
    }
    Py_END_ALLOW_THREADS
    release_all();

    if (!error.empty()) {
        PyErr_SetString(PyExc_RuntimeError, error.c_str());
        return nullptr;
    }
    Py_RETURN_NONE;
}

PyMethodDef METHODS[] = {
    {"create", reinterpret_cast<PyCFunction>(py_create),
        METH_VARARGS | METH_KEYWORDS, nullptr},
    {"integrate", reinterpret_cast<PyCFunction>(py_integrate),
        METH_VARARGS | METH_KEYWORDS, nullptr},
    {"snapshot", py_snapshot, METH_VARARGS, nullptr},
    {"stats", py_stats, METH_VARARGS, nullptr},
    {"write_ply_atomic", reinterpret_cast<PyCFunction>(py_write_ply),
        METH_VARARGS | METH_KEYWORDS, nullptr},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef MODULE = {
    PyModuleDef_HEAD_INIT,
    "_mapping_native",
    "Nodrix C++20 metric mapping data plane",
    -1,
    METHODS,
};

}  // namespace

PyMODINIT_FUNC PyInit__mapping_native() {
    return PyModule_Create(&MODULE);
}
