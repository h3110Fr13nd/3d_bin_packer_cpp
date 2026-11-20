#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/operators.h>  // Include this header for py::self
#include <algorithm>
#include <cctype>
#include <sstream>
#include "box.h"
#include "item.h"
// Make sure we're including the correct bin.h
#include "bin.h"
// Ensure packer.h is included from the right path
#include "../include/packer.h" // or "packer.h" if in the same directory

namespace py = pybind11;

namespace {
// Copies of the packer's bins. A Bin refers to items owned by the Packer, so
// every returned Bin keeps the Packer alive (no dangling references when the
// packer goes out of scope first).
py::list binsKeepingPackerAlive(py::object self) {
    const Packer& packer = self.cast<const Packer&>();
    py::list result;
    for (const Bin& bin : packer.getBins()) {
        py::object obj = py::cast(bin, py::return_value_policy::copy);
        py::detail::keep_alive_impl(obj, self);
        result.append(obj);
    }
    return result;
}
// The items of a bin, as references that keep the bin alive: a Bin refers to
// Items owned by its Packer (kept alive by the Bin, see binsKeepingPackerAlive).
py::list itemsKeepingBinAlive(py::object self) {
    const Bin& bin = self.cast<const Bin&>();
    py::list result;
    for (const auto& ref : bin.getItems()) {
        py::object obj = py::cast(&ref.get(), py::return_value_policy::reference);
        py::detail::keep_alive_impl(obj, self);
        result.append(obj);
    }
    return result;
}

// Shape from its name, case-insensitive: "sphere", "pyramid", "cone",
// "cylinder", "box" (or "cuboid").
Shape shapeFromName(std::string name) {
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
    if (name == "box" || name == "cuboid") return Shape::Box;
    if (name == "sphere") return Shape::Sphere;
    if (name == "pyramid") return Shape::Pyramid;
    if (name == "cone") return Shape::Cone;
    if (name == "cylinder") return Shape::Cylinder;
    throw py::value_error("unknown shape '" + name + "': expected box, sphere, pyramid, cone or cylinder");
}

// Item.shape accepts a Shape or its name; a misspelt name raises a clear ValueError.
Shape toShape(const py::handle& value) {
    if (py::isinstance<py::str>(value)) return shapeFromName(value.cast<std::string>());
    if (py::isinstance<Shape>(value)) return value.cast<Shape>();
    throw py::type_error("shape must be a Shape or its name (\"sphere\", \"cone\", ...), not " +
                         std::string(py::str(py::type::of(value).attr("__name__"))));
}
}  // namespace

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

    py::enum_<Shape>(m, "Shape",
        "Physical shape of an item, used for drawing only: the packer treats every item as its\n"
        "w x h x d box (a thin carton). Cylinders, cones and pyramids stand on their base with\n"
        "the axis / apex along the item's height. Strings like \"sphere\" are accepted too.")
        .value("BOX", Shape::Box)
        .value("SPHERE", Shape::Sphere)
        .value("PYRAMID", Shape::Pyramid)
        .value("CONE", Shape::Cone)
        .value("CYLINDER", Shape::Cylinder)
        .def(py::init(&shapeFromName), py::arg("name"));

    m.attr("ALL_ROTATIONS") = ALL_ROTATIONS;
    m.attr("UPRIGHT_ROTATIONS") = UPRIGHT_ROTATIONS;

    py::enum_<FillOrder>(m, "FillOrder",
        "Which side of the bin is filled first, second and third.\n"
        "BACK_BOTTOM_LEFT = back first (wall building, nose to door, default);\n"
        "BOTTOM_BACK_LEFT = bottom first (complete floor layers).")
        .value("BOTTOM_BACK_LEFT", FillOrder::BottomBackLeft)
        .value("BOTTOM_LEFT_BACK", FillOrder::BottomLeftBack)
        .value("BACK_BOTTOM_LEFT", FillOrder::BackBottomLeft)
        .value("BACK_LEFT_BOTTOM", FillOrder::BackLeftBottom)
        .value("LEFT_BOTTOM_BACK", FillOrder::LeftBottomBack)
        .value("LEFT_BACK_BOTTOM", FillOrder::LeftBackBottom);

    py::enum_<LoadingAccess>(m, "LoadingAccess",
        "Side the bin is loaded from; the loading sequence is feasible for it.")
        .value("DOOR", LoadingAccess::Door)
        .value("TOP", LoadingAccess::Top)
        .value("LEFT_SIDE", LoadingAccess::LeftSide)
        .value("RIGHT_SIDE", LoadingAccess::RightSide)
        .value("NONE", LoadingAccess::None);

    py::enum_<Objective>(m, "Objective", "What to maximise when not everything fits.")
        .value("VOLUME", Objective::Volume)
        .value("WEIGHT", Objective::Weight)
        .value("VALUE", Objective::Value)
        .value("COUNT", Objective::Count)
        .value("PROFIT", Objective::Profit);

    py::enum_<FleetGoal>(m, "FleetGoal", "What the fleet planner minimises once the cargo is loaded.")
        .value("MIN_COST", FleetGoal::Cost)
        .value("MIN_COUNT", FleetGoal::Count);

    m.attr("UNLIMITED") = py::none();

    py::class_<Item, Box>(m, "Item")
        // Positional order is unchanged from earlier versions; every argument
        // after the dimensions can also be given by keyword.
        .def(py::init([](const std::string& name, long w, long h, long d,
                         const std::vector<RotationType>& allowed_rotations, const std::string& color, float weight,
                         int stuffing_layers, float stuffing_max_weight, long stuffing_height, bool bottom_load_only,
                         bool disable_stacking, bool upright, float value, int priority, const std::string& group,
                         const py::object& shape, bool crate_required) {
                 return new Item(name, w, h, d, allowed_rotations, color, weight, stuffing_layers,
                                 stuffing_max_weight, stuffing_height, bottom_load_only, disable_stacking, upright,
                                 value, priority, group, toShape(shape), crate_required);
             }),
             py::arg("name"), py::arg("w"), py::arg("h"), py::arg("d"),
             py::arg("allowed_rotations") = std::vector<RotationType>{},
             py::arg("color") = "#000000", py::arg("weight") = 0.0f,
             py::arg("stuffing_layers") = 0, py::arg("stuffing_max_weight") = 0.0f,
             py::arg("stuffing_height") = 0,
             py::arg("bottom_load_only") = false, py::arg("disable_stacking") = false,
             py::arg("upright") = false, py::arg("value") = 0.0f, py::arg("priority") = 0,
             py::arg("group") = "", py::arg("shape") = Shape::Box, py::arg("crate_required") = false)
        // Legacy shortcut: Item(name, w, h, d, color)
        .def(py::init([](const std::string& name, long w, long h, long d, const std::string& color) {
            return new Item(name, w, h, d, std::vector<RotationType>{}, color);
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
        .def("is_upright", &Item::isUpright)
        .def("set_upright", &Item::setUpright)
        .def("get_effective_rotations", &Item::getEffectiveRotations)
        .def_property("bottom_load_only", &Item::isBottomLoadOnlyEnabled, &Item::setBottomLoadOnly)
        .def_property("disable_stacking", &Item::isDisableStackingEnabled, &Item::setDisableStacking)
        .def_property("upright", &Item::isUpright, &Item::setUpright)
        .def_readwrite("value", &Item::value)
        .def_readwrite("priority", &Item::priority)
        .def_readwrite("group", &Item::group)
        .def_readwrite("crate_required", &Item::crate_required)
        .def_readwrite("crate_index", &Item::crate_index)
        .def_property("shape", [](const Item& item) { return item.shape; },
                      [](Item& item, const py::object& shape) { item.shape = toShape(shape); })
        .def_readonly("unfit_reason", &Item::unfit_reason)
        .def(py::self == py::self)
        .def("__str__", [](const Item &item) {
            std::ostringstream oss;
            oss << item;
            return oss.str();
        })
        .def("__repr__", [](const Item &item) {
            std::ostringstream oss;
            oss << "<" << item << " at (" << std::get<0>(item.getPosition()) << ", "
                << std::get<1>(item.getPosition()) << ", " << std::get<2>(item.getPosition()) << ")>";
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
        .def(py::init<const std::string&, long, long, long, float, const std::string&, const std::string&, int, float>(),
             py::arg("name"), py::arg("w"), py::arg("h"), py::arg("d"), py::arg("max_weight") = 0.0f,
             py::arg("image") = "", py::arg("description") = "", py::arg("id") = 0, py::arg("cost") = 0.0f)
        .def_readwrite("cost", &Bin::cost)
        .def_readonly("type_index", &Bin::type_index)
        // Items are references into the bin's owner: each keeps the Bin (and so its Packer) alive.
        .def("get_items", &itemsKeepingBinAlive)
        .def("set_items", &Bin::setItems)
        .def("score_rotation", &Bin::scoreRotation)
        .def("get_best_rotation_order", &Bin::getBestRotationOrder)
        .def("put_item", &Bin::putItem)
        .def("add_item", &Bin::addItem)
        .def("remove_item", &Bin::removeItem)
        .def_property("items", &itemsKeepingBinAlive,
                      [](Bin& bin, const std::vector<std::reference_wrapper<Item>>& items) { bin.items = items; })
        .def_readwrite("name", &Box::name, py::return_value_policy::reference)
        .def_readwrite("width", &Box::width)
        .def_readwrite("height", &Box::height)
        .def_readwrite("depth", &Box::depth)
        .def_readwrite("max_weight", &Bin::max_weight)
        .def_readwrite("image", &Bin::image)
        .def_readwrite("description", &Bin::description)
        .def_readwrite("id", &Bin::id)
        .def("to_string", &Bin::toString)
        .def("get_total_weight", &Bin::getTotalWeight)
        .def("get_packed_volume", &Bin::getPackedVolume)
        .def("get_utilization", &Bin::getUtilization)
        .def("check_loading_sequence", &Bin::checkLoadingSequence, py::arg("access") = LoadingAccess::Door,
             "Problems with loading the items in their current order from `access`; empty = feasible.")
        .def("reorder_for_loading", &Bin::reorderForLoading, py::arg("access") = LoadingAccess::Door,
             "Re-orders the items into a feasible loading sequence for `access`.")
        .def("__repr__", &Bin::toString);

    py::class_<Packer::BinType>(m, "BinType", "A container type available to the fleet planner.")
        .def_readonly("bin", &Packer::BinType::bin)
        .def_property_readonly("count", [](const Packer::BinType& t) -> py::object {
            if (t.count < 0) return py::none();
            return py::int_(t.count);
        })
        .def("__repr__", [](const Packer::BinType& t) {
            return "<BinType " + t.bin.name + " x " + (t.count < 0 ? std::string("unlimited") : std::to_string(t.count)) + ">";
        });

    py::class_<Packer>(m, "Packer")
        .def(py::init([](FillOrder fill_order, double min_support_ratio, bool non_stackable_on_top,
                         bool optimize, LoadingAccess loading_access, Objective objective, FleetGoal fleet_goal) {
                 PackingConfig config;
                 config.fill_order = fill_order;
                 config.min_support_ratio = min_support_ratio;
                 config.non_stackable_on_top = non_stackable_on_top;
                 config.optimize = optimize;
                 config.loading_access = loading_access;
                 config.objective = objective;
                 config.fleet_goal = fleet_goal;
                 return new Packer(config);
             }),
             py::arg("fill_order") = PackingConfig{}.fill_order,
             py::arg("min_support_ratio") = PackingConfig{}.min_support_ratio,
             py::arg("non_stackable_on_top") = PackingConfig{}.non_stackable_on_top,
             py::arg("optimize") = PackingConfig{}.optimize,
             py::arg("loading_access") = PackingConfig{}.loading_access,
             py::arg("objective") = PackingConfig{}.objective,
             py::arg("fleet_goal") = PackingConfig{}.fleet_goal)
        .def_property("fleet_goal", &Packer::getFleetGoal, &Packer::setFleetGoal)
        .def("add_bin_type", [](Packer& packer, const Bin& bin, std::optional<int> count) {
                 packer.addBinType(bin, count ? *count : Packer::UNLIMITED);
             }, py::arg("bin"), py::arg("count") = py::none(),
             "Container type the fleet planner may book `count` times (None = unlimited).")
        .def("get_bin_types", &Packer::getBinTypes)
        .def("get_total_cost", &Packer::getTotalCost, "Cost of the bins that received items.")
        .def_property("optimize", &Packer::getOptimize, &Packer::setOptimize)
        .def_property("loading_access", &Packer::getLoadingAccess, &Packer::setLoadingAccess)
        .def_property("objective", &Packer::getObjective, &Packer::setObjective)
        .def_property("fill_order", &Packer::getFillOrder, &Packer::setFillOrder)
        .def_property("min_support_ratio", &Packer::getMinSupportRatio, &Packer::setMinSupportRatio)
        .def_property("non_stackable_on_top", &Packer::getNonStackableOnTop, &Packer::setNonStackableOnTop)
        // Bins reference the packer's items: each returned Bin keeps the packer alive.
        .def("get_bins", &binsKeepingPackerAlive)
        .def("get_items", &Packer::getItems)
        .def("get_unfit_items", &Packer::getUnfitItems)
        .def("add_bin", &Packer::addBin)
        .def("add_item", &Packer::addItem)
        .def("find_fitted_bin", &Packer::findFittedBin)
        .def("get_bigger_bin_than", &Packer::getBiggerBinThan)
        .def("unfit_item", &Packer::unfitItem)
        .def("pack_to_bin", &Packer::packToBin)
        .def("pack", &Packer::pack)
        .def_property("bins", &binsKeepingPackerAlive,
                      [](Packer& packer, const std::vector<Bin>& bins) { packer.bins = bins; })
        .def_readwrite("items", &Packer::items)
        .def_readwrite("unfit_items", &Packer::unfit_items);
}
