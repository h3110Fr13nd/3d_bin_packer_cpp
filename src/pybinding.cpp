#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/operators.h>  // Include this header for py::self
#include <sstream>
#include "box.h"
#include "item.h"
#include "bin.h"
#include "packer.h"

namespace py = pybind11;

PYBIND11_MODULE(pybinding, m) {
    py::class_<Box>(m, "Box")
        .def(py::init<const std::string&, float, float, float>())
        .def("get_name", &Box::getName)
        .def("get_width", &Box::getWidth)
        .def("get_height", &Box::getHeight)
        .def("get_depth", &Box::getDepth)
        .def("get_volume", &Box::getVolume);

    py::enum_<RotationType>(m, "RotationType")
        .value("whd", RotationType::whd)
        .value("hwd", RotationType::hwd)
        .value("hdw", RotationType::hdw)
        .value("dhw", RotationType::dhw)
        .value("dwh", RotationType::dwh)
        .value("wdh", RotationType::wdh);

    py::enum_<Axis>(m, "Axis")
        .value("width", Axis::width)
        .value("height", Axis::height)
        .value("depth", Axis::depth);

    py::class_<Item, Box>(m, "Item")
        .def(py::init([](const std::string& name, float w, float h, float d) {
            return new Item(name, w, h, d);
        }))
        .def(py::init([](const std::string& name, float w, float h, float d, 
                        const std::vector<RotationType>& rotations) {
            return new Item(name, w, h, d, rotations);
        }))
        .def(py::init([](const std::string& name, float w, float h, float d,
                        const std::string& color) {
            return new Item(name, w, h, d, std::vector<RotationType>{}, color);
        }))
        .def(py::init([](const std::string& name, float w, float h, float d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color) {
            return new Item(name, w, h, d, rotations, color);
        }))
        .def(py::init<const std::string&, float, float, float, const std::vector<RotationType>&, const std::string&>())
        .def("get_allowed_rotations", &Item::getAllowedRotations)
        .def("get_rotation_type", &Item::getRotationType)
        .def("set_rotation_type", &Item::setRotationType)
        .def("get_position", &Item::getPosition, py::return_value_policy::reference)
        .def("set_position", &Item::setPosition)
        .def("get_rotation_type_string", &Item::getRotationTypeString)
        .def("get_dimension", &Item::getDimension)
        .def("does_intersect", &Item::doesIntersect)
        .def(py::self == py::self)
        .def("__str__", [](const Item &item) {
            std::ostringstream oss;
            oss << item;
            return oss.str();
        });

    py::class_<Bin, Box>(m, "Bin")
        .def(py::init<const std::string&, float, float, float>())
        .def("get_items", &Bin::getItems)
        .def("set_items", &Bin::setItems)
        .def("score_rotation", &Bin::scoreRotation)
        .def("get_best_rotation_order", &Bin::getBestRotationOrder)
        .def("put_item", &Bin::putItem)
        .def("to_string", &Bin::toString);

    py::class_<Packer>(m, "Packer")
        .def(py::init<>())
        .def("get_bins", &Packer::getBins)
        .def("get_items", &Packer::getItems)
        .def("get_unfit_items", &Packer::getUnfitItems)
        .def("add_bin", &Packer::addBin)
        .def("add_item", &Packer::addItem)
        .def("find_fitted_bin", &Packer::findFittedBin)
        .def("get_bigger_bin_than", &Packer::getBiggerBinThan)
        .def("unfit_item", &Packer::unfitItem)
        .def("pack_to_bin", &Packer::packToBin)
        .def("pack", &Packer::pack);
}
