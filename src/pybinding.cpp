#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/operators.h>  // Include this header for py::self
#include <sstream>
#include "box.h"
#include "item.h"
// Make sure we're including the correct bin.h
#include "bin.h"
// Ensure packer.h is included from the right path
#include "../include/packer.h" // or "packer.h" if in the same directory

namespace py = pybind11;

PYBIND11_MODULE(pybinding, m) {
    py::class_<Box>(m, "Box")
        .def(py::init<const std::string&, long, long, long>())
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
        .def(py::init([](const std::string& name, long w, long h, long d) {
            return new Item(name, w, h, d);
        }))
        .def(py::init([](const std::string& name, long w, long h, long d, 
                        const std::vector<RotationType>& rotations) {
            return new Item(name, w, h, d, rotations);
        }))
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::string& color) {
            return new Item(name, w, h, d, std::vector<RotationType>{}, color);
        }))
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color) {
            return new Item(name, w, h, d, rotations, color);
        }))
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color, float weight) {
            return new Item(name, w, h, d, rotations, color, weight);
        }))
        // Add constructors with stuffing parameters
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color, float weight,
                        int stuffing_layers) {
            return new Item(name, w, h, d, rotations, color, weight, stuffing_layers);
        }))
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color, float weight,
                        int stuffing_layers, float stuffing_max_weight) {
            return new Item(name, w, h, d, rotations, color, weight, stuffing_layers, stuffing_max_weight);
        }))
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color, float weight,
                        int stuffing_layers, float stuffing_max_weight, long stuffing_height) {
            return new Item(name, w, h, d, rotations, color, weight, stuffing_layers, stuffing_max_weight, stuffing_height);
        }))
        .def(py::init<const std::string&, long, long, long, const std::vector<RotationType>&, const std::string&>())
        .def(py::init([](const std::string& name, long w, long h, long d,
                        const std::vector<RotationType>& rotations,
                        const std::string& color, float weight,
                        int stuffing_layers, float stuffing_max_weight, long stuffing_height,
                        bool bottom_load_only, bool disable_stacking) {
            return new Item(name, w, h, d, rotations, color, weight, stuffing_layers, 
                          stuffing_max_weight, stuffing_height, bottom_load_only, disable_stacking);
        }))
        .def("get_name", &Item::getName)
        .def("get_allowed_rotations", &Item::getAllowedRotations)
        .def("get_rotation_type", &Item::getRotationType)
        .def("set_rotation_type", &Item::setRotationType)
        .def("get_position", &Item::getPosition, py::return_value_policy::reference)
        .def("set_position", &Item::setPosition)
        .def("get_rotation_type_string", &Item::getRotationTypeString)
        .def("get_dimension", &Item::getDimension)
        .def("does_intersect", &Item::doesIntersect)
        // Add stuffing getter/setter methods
        .def("get_stuffing_layers", &Item::getStuffingLayers)
        .def("set_stuffing_layers", &Item::setStuffingLayers)
        .def("get_stuffing_max_weight", &Item::getStuffingMaxWeight)
        .def("set_stuffing_max_weight", &Item::setStuffingMaxWeight)
        .def("get_stuffing_height", &Item::getStuffingHeight)
        .def("set_stuffing_height", &Item::setStuffingHeight)
        .def("is_bottom_load_only", &Item::isBottomLoadOnlyEnabled)
        .def("set_bottom_load_only", &Item::setBottomLoadOnly)
        .def("is_disable_stacking", &Item::isDisableStackingEnabled)
        .def("set_disable_stacking", &Item::setDisableStacking)
        .def(py::self == py::self)
        .def("__str__", [](const Item &item) {
            std::ostringstream oss;
            oss << item;
            return oss.str();
        })
        .def_readwrite("color", &Item::color)
        .def_readwrite("width", &Item::width)
        .def_readwrite("height", &Item::height)
        .def_readwrite("depth", &Item::depth)
        .def_readwrite("allowed_rotations", &Item::_allowed_rotations)
        .def_readwrite("position", &Item::_position, py::return_value_policy::reference)
        .def_readwrite("rotation_type", &Item::_rotation_type)
        .def_readwrite("name", &Item::name, py::return_value_policy::reference)
        .def_readwrite("weight", &Item::weight)
        // Add stuffing properties
        .def_readwrite("stuffing_layers", &Item::_stuffing_layers)
        .def_readwrite("stuffing_max_weight", &Item::_stuffing_max_weight)
        .def_readwrite("stuffing_height", &Item::_stuffing_height)
        // Add height constraint methods
        .def("is_height_constrained", &Item::isHeightConstrained)
        .def("set_height_constraint", &Item::setHeightConstraint)
        .def("get_height_constraint_value", &Item::getHeightConstraintValue)
        .def("set_height_constraint_type", [](Item& item, int type) {
            HeightConstraintType constraintType = (type == 1) ? 
                HeightConstraintType::EXACT : HeightConstraintType::MAXIMUM;
            item.setHeightConstraintType(constraintType);
        })
        .def("get_height_constraint_type", [](const Item& item) {
            return static_cast<int>(item.getHeightConstraintType());
        });

    py::class_<Bin, Box>(m, "Bin")
        .def(py::init<const std::string&, long, long, long, float, const std::string&, const std::string&, int>(),
             py::arg("name"), py::arg("w"), py::arg("h"), py::arg("d"), py::arg("max_weight") = 0.0f, 
             py::arg("image") = "", py::arg("description") = "", py::arg("id") = 0)
        .def("get_items", &Bin::getItems)
        .def("set_items", &Bin::setItems)
        .def("score_rotation", &Bin::scoreRotation)
        .def("get_best_rotation_order", &Bin::getBestRotationOrder)
        .def("put_item", &Bin::putItem)
        .def("add_item", &Bin::addItem)
        .def("remove_item", &Bin::removeItem)
        .def_readwrite("items", &Bin::items)
        .def_readwrite("name", &Box::name, py::return_value_policy::reference)
        .def_readwrite("width", &Box::width)
        .def_readwrite("height", &Box::height)
        .def_readwrite("depth", &Box::depth)
        .def_readwrite("max_weight", &Bin::max_weight)
        .def_readwrite("image", &Bin::image)
        .def_readwrite("description", &Bin::description)
        .def_readwrite("id", &Bin::id)
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
        .def("pack", &Packer::pack)
        .def_readwrite("bins", &Packer::bins)
        .def_readwrite("items", &Packer::items)
        .def_readwrite("unfit_items", &Packer::unfit_items);
}
