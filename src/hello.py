import pybinding
import bin_packer

# print("pybinding Item:", pybinding.Item('Item 1', 15., 5., 5., [pybinding.RotationType.whd], "red"))
# print("pybinding Bin:", pybinding.Bin('Le grande box', 10000000., 10000000., 30000000.))
# print("pybinding Packer instance:", pybinding.Packer())

packer = pybinding.Packer()
packer.add_bin(pybinding.Bin('Le grande box', 100., 100., 300.))
for i in range(20):
    packer.add_item(pybinding.Item(f'Item {i}', 100., 50., 50.))

packer.pack()
print("packed bins:", packer.get_bins())
print("unfit items:", packer.get_unfit_items(), len(packer.get_unfit_items()))
print("all items:", packer.get_items())
for bin_ in packer.get_bins():
    print("items in bin:", bin_.get_items(), len(bin_.get_items()))
    for item in bin_.get_items():
        print("item position:", item.get_position(), type(item.get_position()))
        # print("item position:", item.get_pos(), type(item.get_pos()))

        # print("item position:", int(item.get_position()[0]), int(item.get_position()[1]), int(item.get_position()[2]))

        # print("item rotation type:", item.get_rotation_type(), type(item.get_rotation_type()))
        # print("item dimension:", item.get_dimension(), type(item.get_dimension()))

print()
packer = bin_packer.Packer()
packer.add_bin(bin_packer.Bin('Le grande box', 100., 100., 300.))
for i in range(20):
    packer.add_item(bin_packer.Item(f'Item {i}', 100., 50., 50.))

packer.pack()
print("packed bins:", packer.bins)
print("unfit items:", packer.unfit_items, len(packer.unfit_items))
print("all items:", packer.items)
for bin_ in packer.bins:
    print("items in bin:", bin_.items, len(bin_.items))
